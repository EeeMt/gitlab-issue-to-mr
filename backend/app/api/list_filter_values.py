"""Shared parsing and validation for list endpoint filter values."""

from datetime import UTC, datetime

from fastapi import HTTPException


def parse_csv_integers(
    value: str,
    field: str,
    *,
    minimum: int | None = None,
    allowed: set[int] | None = None,
) -> list[int]:
    """Parse a comma-separated integer filter without silently broadening a query."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    parsed: list[int] = []
    invalid: list[str] = []
    for part in parts:
        try:
            number = int(part)
        except ValueError:
            invalid.append(part)
            continue
        if (minimum is not None and number < minimum) or (
            allowed is not None and number not in allowed
        ):
            invalid.append(part)
            continue
        parsed.append(number)

    if not parts or invalid:
        detail = f"Invalid {field} value(s): {', '.join(invalid or [value])}"
        if allowed is not None:
            detail += f". Allowed: {', '.join(str(item) for item in sorted(allowed))}"
        raise HTTPException(status_code=400, detail=detail)

    return list(dict.fromkeys(parsed))


def normalize_search_term(value: str, *, max_length: int = 200) -> str | None:
    """Trim a search term and return only terms long enough to apply."""
    term = value.strip()
    if len(term) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"search too long (max {max_length} characters)",
        )
    return term if len(term) >= 2 else None


def parse_datetime_filter(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value}") from exc


def validate_datetime_range(
    after: datetime | None,
    before: datetime | None,
    after_field: str,
    before_field: str,
) -> None:
    if after is not None and before is not None and after > before:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date range: {after_field} must not be after {before_field}",
        )
