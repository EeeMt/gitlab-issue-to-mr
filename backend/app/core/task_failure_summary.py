"""Concise failure summary derived from canonical Task terminal events."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.worker import sanitize_sensitive_data
from app.models import TaskHarnessAttempt, TaskHarnessEventReceipt

_MAX_FAILURE_MESSAGE_LENGTH = 1000


async def load_task_failure_summary(
    db: AsyncSession,
    task_id: int,
) -> dict[str, str | None]:
    """Return failure kind/message from the latest canonical ``run.failed`` terminal."""
    attempt_id = (
        await db.execute(
            select(TaskHarnessAttempt.attempt_id)
            .where(TaskHarnessAttempt.task_id == task_id)
            .order_by(TaskHarnessAttempt.attempt_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if attempt_id is None:
        return {"failure_kind": None, "failure_message": None}

    event = (
        await db.execute(
            select(TaskHarnessEventReceipt.event)
            .where(
                TaskHarnessEventReceipt.attempt_id == attempt_id,
                TaskHarnessEventReceipt.event_type == "run.failed",
            )
            .order_by(TaskHarnessEventReceipt.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(event, dict):
        return {"failure_kind": None, "failure_message": None}

    payload = event.get("payload")
    if not isinstance(payload, dict):
        return {"failure_kind": None, "failure_message": None}

    failure = payload.get("failure")
    kind = ""
    message = ""
    if isinstance(failure, dict):
        kind = str(failure.get("kind") or "")
        message = str(failure.get("message") or "")
    kind = kind or str(payload.get("status") or "")

    return {
        "failure_kind": (
            sanitize_sensitive_data(kind)[:_MAX_FAILURE_MESSAGE_LENGTH] or None
        ),
        "failure_message": (
            sanitize_sensitive_data(message)[:_MAX_FAILURE_MESSAGE_LENGTH] or None
        ),
    }
