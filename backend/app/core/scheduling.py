"""Scheduling helpers for task creation."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Optional


def normalize_scheduled_datetime(scheduled_datetime: Optional[datetime]) -> Optional[datetime]:
    """Convert scheduled datetimes to naive UTC for database storage."""
    if scheduled_datetime is None:
        return None

    if scheduled_datetime.tzinfo is None or scheduled_datetime.utcoffset() is None:
        return scheduled_datetime

    return scheduled_datetime.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_scheduled_at(
    scheduled_datetime: Optional[datetime],
    delay_seconds: Optional[int],
) -> Optional[datetime]:
    """Resolve the final scheduled execution time."""
    if scheduled_datetime:
        return normalize_scheduled_datetime(scheduled_datetime)

    if delay_seconds:
        return datetime.now(UTC) + timedelta(seconds=delay_seconds)

    return None
