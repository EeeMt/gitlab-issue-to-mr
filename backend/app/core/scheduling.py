"""Scheduling helpers for task creation."""

from datetime import UTC, datetime, timedelta

from app.core.utcnow import utcnow


def normalize_scheduled_datetime(scheduled_datetime: datetime | None) -> datetime | None:
    """Convert scheduled datetimes to naive UTC for database storage."""
    if scheduled_datetime is None:
        return None

    if scheduled_datetime.tzinfo is None or scheduled_datetime.utcoffset() is None:
        return scheduled_datetime

    return scheduled_datetime.astimezone(UTC).replace(tzinfo=None)


def resolve_scheduled_at(
    scheduled_datetime: datetime | None,
    delay_seconds: int | None,
) -> datetime | None:
    """Resolve the final scheduled execution time."""
    if scheduled_datetime:
        return normalize_scheduled_datetime(scheduled_datetime)

    if delay_seconds:
        return utcnow() + timedelta(seconds=delay_seconds)

    return None
