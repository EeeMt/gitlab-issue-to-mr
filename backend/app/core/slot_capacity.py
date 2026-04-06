"""Slot capacity checking for time-based task scheduling limits."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)

SLOT_DURATION_HOURS = 1


@dataclass
class SlotCapacityInfo:
    """Capacity information for a single time slot."""

    hour_start: datetime
    hour_end: datetime
    count: int
    max: int
    is_full: bool
    enforce: bool


def _get_slot_boundaries(scheduled_at: datetime) -> tuple[datetime, datetime]:
    """Return the 1-hour slot boundaries for a given datetime."""
    from datetime import timedelta
    hour_start = scheduled_at.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=SLOT_DURATION_HOURS)
    return hour_start, hour_end


def _slot_lock_key(hour_start: datetime) -> int:
    """Derive a stable int64 advisory lock key from slot start time."""
    tag = f"slot:{hour_start.isoformat()}"
    return int(hashlib.md5(tag.encode()).hexdigest()[:15], 16)


async def check_slot_capacity(
    db: AsyncSession,
    scheduled_at: datetime,
    *,
    exclude_task_id: int | None = None,
    acquire_lock: bool = False,
) -> SlotCapacityInfo:
    """Check how many active tasks are scheduled in the same 1-hour slot.

    Args:
        db: Database session.
        scheduled_at: The target scheduled time.
        exclude_task_id: Task ID to exclude from count (for reschedule).
        acquire_lock: If True, acquire a pg_advisory_xact_lock to prevent
            TOCTOU races between concurrent capacity checks and inserts.
            Use True when the caller will INSERT a task after this check.

    Returns:
        SlotCapacityInfo with current count, max, and full status.
    """
    settings = get_effective_settings()
    max_tasks = settings.slot_max_tasks
    enforce = settings.slot_max_tasks_enforce

    hour_start, hour_end = _get_slot_boundaries(scheduled_at)

    # Serialize concurrent checks for the same slot to prevent TOCTOU races
    if acquire_lock and max_tasks > 0:
        lock_key = _slot_lock_key(hour_start)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    query = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.scheduled_at.is_not(None),
            Task.scheduled_at >= hour_start,
            Task.scheduled_at < hour_end,
            Task.status.in_([
                TaskStatus.PENDING,
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
            ]),
        )
    )
    if exclude_task_id is not None:
        query = query.where(Task.id != exclude_task_id)

    result = await db.execute(query)
    count = result.scalar() or 0

    is_full = max_tasks > 0 and count >= max_tasks

    return SlotCapacityInfo(
        hour_start=hour_start,
        hour_end=hour_end,
        count=count,
        max=max_tasks,
        is_full=is_full,
        enforce=enforce,
    )


def format_slot_rejection_message(info: SlotCapacityInfo) -> str:
    """Format a human-readable rejection message for GitLab comments."""
    start_str = info.hour_start.strftime("%Y-%m-%d %H:%M")
    end_str = info.hour_end.strftime("%H:%M")
    return (
        f"⚠️ Time slot **{start_str}–{end_str}** is at full capacity "
        f"({info.count}/{info.max} tasks). Task creation was rejected.\n\n"
        f"Please choose a different time slot or contact an administrator "
        f"to adjust the `slot_max_tasks` limit."
    )


def format_slot_full_detail(info: SlotCapacityInfo) -> str:
    """Plain-text capacity message for GitLab comments and logs."""
    start_str = info.hour_start.strftime("%Y-%m-%d %H:%M")
    end_str = info.hour_end.strftime("%H:%M")
    return (
        f"Time slot {start_str}–{end_str} is at full capacity "
        f"({info.count}/{info.max} tasks)"
    )


def slot_full_detail_dict(info: SlotCapacityInfo) -> dict:
    """Structured capacity detail for HTTP 409 responses.

    Returns a dict so the frontend can format with proper timezone and locale.
    """
    return {
        "code": "SLOT_FULL",
        "hour_start": info.hour_start.isoformat(),
        "hour_end": info.hour_end.isoformat(),
        "count": info.count,
        "max": info.max,
    }
