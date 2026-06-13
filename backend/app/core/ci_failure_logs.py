"""Structured step logging for CI failure collection."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CIFailureRun, CIFailureRunLog


async def append_ci_failure_log(
    db: AsyncSession,
    run: CIFailureRun,
    *,
    step: str,
    status: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    task_id: int | None = None,
) -> CIFailureRunLog:
    """Append one product-visible CI failure timeline entry."""
    log = CIFailureRunLog(
        ci_failure_run_id=run.id,
        issue_id=run.issue_id,
        task_id=task_id,
        step=step,
        status=status,
        message=message,
        details=details,
    )
    db.add(log)
    await db.flush()
    return log
