"""Transactional Harness attempt and canonical event ingest primitives."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    TASK_TERMINAL_TYPES,
    CanonicalEventReplay,
    HarnessProtocolError,
    content_digest,
    validate_event,
)
from app.core.utcnow import utcnow
from app.models import Task, TaskHarnessAttempt, TaskHarnessEventReceipt


@dataclass(frozen=True, slots=True)
class EventIngestResult:
    event: dict
    attempt: TaskHarnessAttempt
    duplicate: bool


def new_attempt_id(task_id: int, attempt_no: int) -> str:
    return f"task-{task_id}-attempt-{attempt_no}-{uuid4().hex[:12]}"


async def create_task_attempt(
    db: AsyncSession,
    *,
    task: Task,
    harness_key: str,
    adapter_version: str,
    cli_version: str | None = None,
    attempt_id: str | None = None,
) -> TaskHarnessAttempt:
    """Create the task-owned attempt or reuse it after scheduler recovery."""
    existing = (
        await db.execute(
            select(TaskHarnessAttempt)
            .where(TaskHarnessAttempt.task_id == task.id)
            .order_by(TaskHarnessAttempt.attempt_no.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.harness_key != harness_key or existing.adapter_version != adapter_version:
            raise HarnessProtocolError(
                "scheduler recovery attempted to change the frozen Harness Adapter"
            )
        return existing

    created = TaskHarnessAttempt(
        attempt_id=attempt_id or new_attempt_id(task.id, 1),
        task_id=task.id,
        attempt_no=1,
        event_schema=CANONICAL_EVENT_SCHEMA,
        harness_key=harness_key,
        adapter_version=adapter_version,
        cli_version=cli_version,
        last_seq=0,
    )
    db.add(created)
    await db.flush()
    return created


async def _load_replay(db: AsyncSession, attempt_id: str) -> CanonicalEventReplay:
    receipts = list(
        (
            await db.execute(
                select(TaskHarnessEventReceipt)
                .where(TaskHarnessEventReceipt.attempt_id == attempt_id)
                .order_by(TaskHarnessEventReceipt.seq)
            )
        ).scalars()
    )
    replay = CanonicalEventReplay()
    for receipt in receipts:
        replay.ingest(receipt.event)
    return replay


async def ingest_canonical_event(
    db: AsyncSession,
    event: dict,
) -> EventIngestResult:
    """Accept one event exactly once, rejecting gaps and divergent duplicates."""
    normalized = validate_event(event)
    attempt = (
        await db.execute(
            select(TaskHarnessAttempt)
            .where(TaskHarnessAttempt.attempt_id == normalized["attempt_id"])
            .with_for_update()
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HarnessProtocolError("canonical event references an unknown attempt")
    if attempt.task_id != normalized["task_id"]:
        raise HarnessProtocolError("canonical event task does not own its attempt")
    if attempt.harness_key != normalized["harness"]["key"]:
        raise HarnessProtocolError("canonical event Harness does not match the frozen attempt")
    if attempt.adapter_version != normalized["harness"]["adapter_version"]:
        raise HarnessProtocolError("canonical event Adapter does not match the frozen attempt")
    event_cli_version = normalized["harness"]["cli_version"]
    if attempt.cli_version is None:
        attempt.cli_version = event_cli_version
    elif attempt.cli_version != event_cli_version:
        raise HarnessProtocolError("canonical event CLI does not match the frozen attempt")
    if attempt.event_schema != normalized["schema"]:
        raise HarnessProtocolError("canonical event schema does not match the frozen attempt")

    digest = content_digest(normalized)
    existing = await db.get(
        TaskHarnessEventReceipt,
        (attempt.attempt_id, normalized["seq"]),
    )
    if existing is not None:
        if existing.event_id != normalized["event_id"] or existing.event_digest != digest:
            raise HarnessProtocolError(
                f"divergent duplicate at sequence {normalized['seq']}",
                code="duplicate_conflict",
            )
        return EventIngestResult(event=normalized, attempt=attempt, duplicate=True)

    replay = await _load_replay(db, attempt.attempt_id)
    replay.ingest(normalized)
    receipt = TaskHarnessEventReceipt(
        attempt_id=attempt.attempt_id,
        seq=normalized["seq"],
        event_id=normalized["event_id"],
        event_type=normalized["type"],
        event_digest=digest,
        event=normalized,
    )
    db.add(receipt)
    attempt.last_seq = normalized["seq"]
    if normalized["type"] in TASK_TERMINAL_TYPES:
        if attempt.terminal_event_id is not None:
            raise HarnessProtocolError("attempt already has a Task terminal")
        attempt.terminal_event_id = normalized["event_id"]
        attempt.terminal_event_type = normalized["type"]
        attempt.terminal_at = utcnow()
    await db.flush()
    return EventIngestResult(event=normalized, attempt=attempt, duplicate=False)


async def assert_attempt_complete(db: AsyncSession, attempt_id: str) -> TaskHarnessAttempt:
    attempt = (
        await db.execute(
            select(TaskHarnessAttempt).where(TaskHarnessAttempt.attempt_id == attempt_id)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HarnessProtocolError("unknown Harness attempt")
    replay = await _load_replay(db, attempt_id)
    terminal = replay.finish()
    if attempt.terminal_event_type != terminal:
        raise HarnessProtocolError("attempt terminal receipt and summary state disagree")
    return attempt
