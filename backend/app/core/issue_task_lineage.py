"""Projected session-lineage resolution and recording.

New Scheduler resolves the resume session through ``IssueSessionLineage`` keyed
by ``(issue_id, lineage_generation)`` with a Harness/namespace consistency check,
never through the legacy ``IssueHarnessSession`` mirror or ``Issue.claude_session_id``
fallback. ``fresh`` clears the generation's session; ``continue`` without a
generation session starts with ``fresh_no_match`` and never falls back to an
older generation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IssueSessionLineage, Task

# input_lineage_reason values recorded at execution time.
INPUT_REASON_FRESH = "fresh"
INPUT_REASON_RESUMED = "resumed"
INPUT_REASON_FRESH_NO_MATCH = "fresh_no_match"


async def get_lineage_row(
    db: AsyncSession,
    *,
    issue_id: int,
    generation: int,
) -> IssueSessionLineage | None:
    return (
        await db.execute(
            select(IssueSessionLineage).where(
                IssueSessionLineage.issue_id == issue_id,
                IssueSessionLineage.lineage_generation == generation,
            )
        )
    ).scalar_one_or_none()


async def ensure_lineage_row(
    db: AsyncSession,
    *,
    issue_id: int,
    generation: int,
    harness_key: str,
    session_namespace: str,
    reset_task_id: int | None,
    lineage_reason: str,
) -> IssueSessionLineage:
    """Get or create the per-generation lineage row inside the caller's lock."""
    row = await get_lineage_row(db, issue_id=issue_id, generation=generation)
    if row is not None:
        return row
    row = IssueSessionLineage(
        issue_id=issue_id,
        lineage_generation=generation,
        harness_key=harness_key,
        session_namespace=session_namespace,
        reset_task_id=reset_task_id,
        lineage_reason=lineage_reason,
    )
    db.add(row)
    await db.flush()
    return row


def projection_for_task(task: Task) -> dict[str, Any] | None:
    """Return the Task's frozen lineage projection tuple, or None if incomplete."""
    if (
        task.projected_harness_key is None
        or task.projected_session_namespace is None
        or task.projected_lineage_generation is None
    ):
        return None
    return {
        "harness_key": task.projected_harness_key,
        "session_namespace": task.projected_session_namespace,
        "generation": task.projected_lineage_generation,
        "reset_task_id": task.projected_reset_task_id,
        "reason": task.lineage_projection_reason,
    }


async def resolve_projected_resume_session(
    db: AsyncSession,
    *,
    task: Task,
    harness_key: str,
    session_namespace: str,
    generation: int,
    reset_task_id: int | None,
    session_mode: str,
) -> tuple[str | None, str]:
    """Resolve ``(resume_session_id, input_lineage_reason)`` before Worker start.

    ``fresh`` clears the generation's session and records ``fresh``. ``continue``
    reads the exact generation row; a matching Harness/namespace with a known
    session resumes it, otherwise the task starts with no resume ID and records
    ``fresh_no_match``. A stale lineage row (different harness/namespace) fails
    closed instead of silently reusing it.
    """
    if session_mode == "fresh":
        row = await ensure_lineage_row(
            db,
            issue_id=task.issue_id,
            generation=generation,
            harness_key=harness_key,
            session_namespace=session_namespace,
            reset_task_id=reset_task_id,
            lineage_reason="fresh",
        )
        row.session_id = None
        row.lineage_reason = "fresh"
        await db.flush()
        return None, INPUT_REASON_FRESH

    row = await get_lineage_row(
        db,
        issue_id=task.issue_id,
        generation=generation,
    )
    if (
        row is not None
        and row.harness_key == harness_key
        and row.session_namespace == session_namespace
        and row.session_id
    ):
        return row.session_id, INPUT_REASON_RESUMED
    return None, INPUT_REASON_FRESH_NO_MATCH


async def record_projected_output_session(
    db: AsyncSession,
    *,
    task: Task,
    session_id: str | None,
) -> None:
    """Record the produced session on the Task's generation lineage row.

    The row must match the Task's frozen harness/namespace/generation; a mismatch
    means the lineage was re-projected since the Task was created and must fail
    closed rather than write into another generation. ``last_output_issue_sequence``
    must stay below the current turn.
    """
    if task.projected_harness_key is None or task.projected_session_namespace is None:
        raise ValueError("Task has no projected lineage to record output against")
    if task.projected_lineage_generation is None:
        raise ValueError("Task has no projected lineage generation")
    row = await get_lineage_row(
        db,
        issue_id=task.issue_id,
        generation=task.projected_lineage_generation,
    )
    if row is None:
        row = await ensure_lineage_row(
            db,
            issue_id=task.issue_id,
            generation=task.projected_lineage_generation,
            harness_key=task.projected_harness_key,
            session_namespace=task.projected_session_namespace,
            reset_task_id=task.projected_reset_task_id,
            lineage_reason=task.lineage_projection_reason or "inherited",
        )
    if (
        row.harness_key != task.projected_harness_key
        or row.session_namespace != task.projected_session_namespace
    ):
        raise ValueError(
            "Lineage row no longer matches the Task projection; refusing to cross generations"
        )
    if (
        row.last_output_issue_sequence is not None
        and task.issue_sequence is not None
        and task.issue_sequence < row.last_output_issue_sequence
    ):
        raise ValueError("Task issue_sequence is behind the generation's last output")
    row.session_id = session_id
    row.last_output_task_id = task.id
    row.last_output_issue_sequence = task.issue_sequence
    await db.flush()
