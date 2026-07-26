"""Tests for shared list-filter value parsing."""

from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api.list_filter_values import (
    normalize_search_term,
    parse_csv_integers,
    parse_datetime_filter,
    validate_datetime_range,
)


def test_parse_datetime_filter_normalizes_offsets_to_naive_utc():
    assert parse_datetime_filter(
        "2026-01-01T00:00:00+08:00",
        "created_after",
    ) == datetime(2025, 12, 31, 16, 0, 0)


def test_parse_datetime_filter_preserves_naive_utc_input():
    assert parse_datetime_filter(
        "2026-01-01T00:00:00",
        "created_after",
    ) == datetime(2026, 1, 1, 0, 0, 0)


def test_parse_csv_integers_deduplicates_valid_values():
    assert parse_csv_integers("2,1,2", "project_id", minimum=1) == [2, 1]


@pytest.mark.parametrize("value", ["abc", "0", "1,abc"])
def test_parse_csv_integers_rejects_invalid_values(value: str):
    with pytest.raises(HTTPException, match="Invalid project_id"):
        parse_csv_integers(value, "project_id", minimum=1)


def test_normalize_search_term_trims_and_ignores_short_terms():
    assert normalize_search_term("  release  ") == "release"
    assert normalize_search_term(" x ") is None


def test_validate_datetime_range_rejects_reversed_bounds():
    with pytest.raises(HTTPException, match="must not be after"):
        validate_datetime_range(
            datetime(2026, 2, 1),
            datetime(2026, 1, 1),
            "created_after",
            "created_before",
        )
