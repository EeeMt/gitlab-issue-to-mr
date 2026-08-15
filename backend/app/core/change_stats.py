"""Change-statistics invariants shared by all writers (design §6.4)."""

from __future__ import annotations

from typing import Any


def validate_change_statistics(
    additions: Any, deletions: Any, total: Any
) -> str | None:
    """Return an error message when the triple is not a consistent known value.

    Accepts real zeros; rejects negatives and totals that do not equal
    ``additions + deletions``. Returns ``None`` when valid.
    """
    try:
        additions_int = int(additions)
        deletions_int = int(deletions)
        total_int = int(total)
    except (TypeError, ValueError):
        return "additions, deletions and total must be integers"
    if additions_int < 0 or deletions_int < 0 or total_int < 0:
        return "change statistics must be non-negative"
    if total_int != additions_int + deletions_int:
        return "total must equal additions + deletions"
    return None
