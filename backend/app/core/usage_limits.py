"""Usage quota resolution and enforcement helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import func, select

from app.models import TaskUsageLedger, UsageLimitPolicy

QUOTA_FIELDS = (
    "daily_tokens",
    "weekly_tokens",
    "daily_tasks",
    "weekly_tasks",
)


@dataclass(frozen=True)
class ResolvedUsageLimit:
    """Resolved quota item after system defaults and user overrides are merged."""

    mode: str
    value: int | None

    @property
    def is_unlimited(self) -> bool:
        return self.mode == "unlimited"


class UsageLimitExceeded(Exception):
    """Raised when a user has already exceeded one or more usage limits."""

    def __init__(self, *, scope: str, exceeded_items: list[dict[str, Any]]) -> None:
        self.scope = scope
        self.exceeded_items = exceeded_items
        super().__init__("usage_limit_exceeded")


class UsageQuotaService:
    """Resolve effective limits and detect quota overages."""

    async def resolve_effective_limits(
        self,
        db: Any,
        user_id: int,
        *,
        system_row: Any | None = None,
        user_row: Any | None = None,
    ) -> dict[str, ResolvedUsageLimit]:
        system_policy = system_row or await self._load_system_policy(db)
        user_policy = user_row or await self._load_user_policy(db, user_id)

        return {
            field: self._resolve_item(system_policy, user_policy, field)
            for field in QUOTA_FIELDS
        }

    async def raise_if_over_limit(
        self,
        db: Any,
        user_id: int,
        *,
        scope: str,
        now: datetime | None = None,
        timezone: tzinfo = UTC,
        effective_limits: dict[str, ResolvedUsageLimit] | None = None,
        usage_totals: dict[str, int] | None = None,
    ) -> None:
        current_time = now or datetime.now(UTC)
        limits = effective_limits or await self.resolve_effective_limits(db, user_id)
        usage = usage_totals or await self.get_current_usage_totals(
            db,
            user_id,
            now=current_time,
            timezone=timezone,
        )
        exceeded_items = self._build_exceeded_items(
            limits,
            usage,
            now=current_time,
            timezone=timezone,
        )
        if exceeded_items:
            raise UsageLimitExceeded(scope=scope, exceeded_items=exceeded_items)

    async def get_current_usage_totals(
        self,
        db: Any,
        user_id: int,
        *,
        now: datetime | None = None,
        timezone: tzinfo = UTC,
    ) -> dict[str, int]:
        current_time = now or datetime.now(UTC)
        timezone_day, timezone_week_start = _calendar_keys_for_datetime(current_time, timezone=timezone)

        daily_result = await db.execute(
            select(
                func.coalesce(func.sum(TaskUsageLedger.total_tokens), 0),
                func.coalesce(func.sum(TaskUsageLedger.task_count), 0),
            ).where(
                TaskUsageLedger.user_id == user_id,
                TaskUsageLedger.timezone_day == timezone_day,
            )
        )
        daily_tokens, daily_tasks = daily_result.one()

        weekly_result = await db.execute(
            select(
                func.coalesce(func.sum(TaskUsageLedger.total_tokens), 0),
                func.coalesce(func.sum(TaskUsageLedger.task_count), 0),
            ).where(
                TaskUsageLedger.user_id == user_id,
                TaskUsageLedger.timezone_week_start == timezone_week_start,
            )
        )
        weekly_tokens, weekly_tasks = weekly_result.one()

        return {
            "daily_tokens": int(daily_tokens or 0),
            "weekly_tokens": int(weekly_tokens or 0),
            "daily_tasks": int(daily_tasks or 0),
            "weekly_tasks": int(weekly_tasks or 0),
        }

    async def _load_system_policy(self, db: Any) -> Any | None:
        result = await db.execute(
            select(UsageLimitPolicy).where(
                UsageLimitPolicy.scope_type == "system_default",
                UsageLimitPolicy.user_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _load_user_policy(self, db: Any, user_id: int) -> Any | None:
        result = await db.execute(
            select(UsageLimitPolicy).where(
                UsageLimitPolicy.scope_type == "user",
                UsageLimitPolicy.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    def _resolve_item(self, system_row: Any | None, user_row: Any | None, field: str) -> ResolvedUsageLimit:
        user_mode = getattr(user_row, f"{field}_mode", None) if user_row is not None else None
        user_value = getattr(user_row, f"{field}_value", None) if user_row is not None else None
        system_mode = getattr(system_row, f"{field}_mode", "unlimited") if system_row is not None else "unlimited"
        system_value = getattr(system_row, f"{field}_value", None) if system_row is not None else None

        if user_mode == "custom":
            return ResolvedUsageLimit(mode="custom", value=user_value)
        if user_mode == "unlimited":
            return ResolvedUsageLimit(mode="unlimited", value=None)
        if user_mode == "inherit":
            return ResolvedUsageLimit(mode=system_mode, value=system_value)

        return ResolvedUsageLimit(mode=system_mode, value=system_value)

    def _build_exceeded_items(
        self,
        limits: dict[str, ResolvedUsageLimit],
        usage: dict[str, int],
        *,
        now: datetime,
        timezone: tzinfo,
    ) -> list[dict[str, Any]]:
        exceeded_items: list[dict[str, Any]] = []
        reset_at = _next_reset_timestamps(now, timezone=timezone)

        for field, limit in limits.items():
            if limit.is_unlimited or limit.value is None:
                continue

            used_value = usage.get(field, 0)
            if used_value <= limit.value:
                continue

            metric = "tokens" if "tokens" in field else "tasks"
            window = "daily" if field.startswith("daily_") else "weekly"
            exceeded_items.append(
                {
                    "field": field,
                    "window": window,
                    "metric": metric,
                    "used": used_value,
                    "limit": limit.value,
                    "reset_at": reset_at[window],
                }
            )

        return exceeded_items


def _calendar_keys_for_datetime(
    value: datetime,
    *,
    timezone: tzinfo = UTC,
) -> tuple[date, date]:
    localized = _to_system_timezone(value, timezone=timezone)
    day_key = localized.date()
    week_start = day_key - timedelta(days=day_key.weekday())
    return day_key, week_start


def _next_reset_timestamps(
    value: datetime,
    *,
    timezone: tzinfo = UTC,
) -> dict[str, str]:
    localized = _to_system_timezone(value, timezone=timezone)
    local_date = localized.date()
    next_day = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=timezone)
    next_week = datetime.combine(
        local_date + timedelta(days=(7 - local_date.weekday())),
        time.min,
        tzinfo=timezone,
    )
    return {
        "daily": next_day.isoformat(),
        "weekly": next_week.isoformat(),
    }


async def upsert_task_usage_ledger(
    db: Any,
    task: Any,
    *,
    timezone: tzinfo = UTC,
) -> None:
    if getattr(task, "initiator_user_id", None) is None or getattr(task, "completed_at", None) is None:
        return
    if getattr(task, "input_tokens", None) is None and getattr(task, "output_tokens", None) is None:
        return

    completed_at = task.completed_at
    timezone_day, timezone_week_start = _calendar_keys_for_datetime(completed_at, timezone=timezone)
    input_tokens = int(getattr(task, "input_tokens", 0) or 0)
    output_tokens = int(getattr(task, "output_tokens", 0) or 0)
    total_tokens = input_tokens + output_tokens

    result = await db.execute(select(TaskUsageLedger).where(TaskUsageLedger.task_id == task.id))
    existing = result.scalar_one_or_none()
    task_status = getattr(task.status, "value", task.status)

    if existing is None:
        db.add(
            TaskUsageLedger(
                task_id=task.id,
                user_id=task.initiator_user_id,
                task_status=str(task_status),
                completed_at=completed_at,
                timezone_day=timezone_day,
                timezone_week_start=timezone_week_start,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                task_count=1,
            )
        )
        return

    existing.user_id = task.initiator_user_id
    existing.task_status = str(task_status)
    existing.completed_at = completed_at
    existing.timezone_day = timezone_day
    existing.timezone_week_start = timezone_week_start
    existing.input_tokens = input_tokens
    existing.output_tokens = output_tokens
    existing.total_tokens = total_tokens
    existing.task_count = 1


def _to_system_timezone(value: datetime, *, timezone: tzinfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)
