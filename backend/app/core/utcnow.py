"""Canonical naive-UTC timestamp helper.

All DB columns use naive (tz-unaware) datetimes that represent UTC.
Use ``utcnow()`` everywhere instead of ``datetime.now(UTC).replace(tzinfo=None)``
to avoid mixing tz-aware and tz-naive datetimes.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo)."""
    return datetime.now(UTC).replace(tzinfo=None)
