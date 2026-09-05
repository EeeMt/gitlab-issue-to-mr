"""Transactional Harness attempt and canonical event ingest primitives."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    HARNESS_TERMINAL_TYPES,
    TASK_TERMINAL_TYPES,
    CanonicalEventReplay,
    HarnessProtocolError,
    content_digest,
    validate_event_by_schema,
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
    event_schema: str = CANONICAL_EVENT_SCHEMA,
    control_state: str = "disabled",
    control_supported: bool = False,
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
        event_schema=event_schema,
        harness_key=harness_key,
        adapter_version=adapter_version,
        cli_version=cli_version,
        last_seq=0,
        control_state=control_state if control_supported else "disabled",
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


async def _existing_event_types(
    db: AsyncSession,
    *,
    attempt_id: str,
    event_types: set[str] | frozenset[str],
) -> set[str]:
    """Return the requested prior event types without replaying the attempt.

    Live ingest is serialized by the attempt row lock.  The full replay remains
    the authoritative one-shot integrity check in :func:`assert_attempt_complete`,
    but loading every receipt for every streamed event makes archive backfill
    quadratic for long model responses.
    """
    if not event_types:
        return set()
    result = await db.execute(
        select(TaskHarnessEventReceipt.event_type)
        .where(
            TaskHarnessEventReceipt.attempt_id == attempt_id,
            TaskHarnessEventReceipt.event_type.in_(event_types),
        )
    )
    return set(result.scalars())


async def _first_event_harness_metadata(
    db: AsyncSession,
    *,
    attempt_id: str,
) -> tuple[object, object] | None:
    """Read the immutable transport/model metadata from the first receipt."""
    first = await db.get(TaskHarnessEventReceipt, (attempt_id, 1))
    if first is None or not isinstance(first.event, dict):
        return None
    harness = first.event.get("harness")
    if not isinstance(harness, dict):
        return None
    return harness.get("control_transport"), harness.get("model_protocols")


async def _event_ids_for_attempt(
    db: AsyncSession,
    *,
    attempt_id: str,
) -> set[str]:
    result = await db.execute(
        select(TaskHarnessEventReceipt.event_id).where(
            TaskHarnessEventReceipt.attempt_id == attempt_id
        )
    )
    return set(result.scalars())


async def _last_event_type(
    db: AsyncSession,
    *,
    attempt: TaskHarnessAttempt,
) -> str | None:
    if attempt.last_seq <= 0:
        return None
    last = await db.get(TaskHarnessEventReceipt, (attempt.attempt_id, attempt.last_seq))
    return last.event_type if last is not None else None


async def _validate_incremental_event_order(
    db: AsyncSession,
    *,
    attempt: TaskHarnessAttempt,
    event: dict,
) -> None:
    """Validate ordering invariants using the locked attempt and small queries."""
    event_type = event["type"]
    if attempt.terminal_event_type is not None:
        raise HarnessProtocolError(
            "canonical event appears after task terminal",
            code="after_terminal",
        )
    expected_seq = attempt.last_seq + 1
    if event["seq"] != expected_seq:
        raise HarnessProtocolError(
            f"sequence gap: expected {expected_seq}, received {event['seq']}",
            code="sequence_gap",
        )

    finalization_seen = getattr(attempt, "_canonical_finalization_seen", None)
    if finalization_seen is None:
        finalization_seen = (
            await _last_event_type(db, attempt=attempt) == "worker.finalization"
        )
        setattr(attempt, "_canonical_finalization_seen", finalization_seen)
    if finalization_seen and event_type not in TASK_TERMINAL_TYPES:
        raise HarnessProtocolError(
            "only the Task terminal may follow worker.finalization",
            code="after_finalization",
        )

    # Cache the immutable V2 transport/model identity on the ORM object for the
    # current ingest session.  A new session simply performs one indexed read.
    if event["seq"] > 1:
        metadata = getattr(attempt, "_canonical_harness_metadata", None)
        if metadata is None:
            metadata = await _first_event_harness_metadata(
                db,
                attempt_id=attempt.attempt_id,
            )
            setattr(attempt, "_canonical_harness_metadata", metadata)
        if metadata is None:
            raise HarnessProtocolError("canonical attempt is missing run.started", code="missing_init")
        control_transport, model_protocols = metadata
        harness = event["harness"]
        if harness.get("control_transport") != control_transport:
            raise HarnessProtocolError("control transport changed inside one replay")
        if harness.get("model_protocols") != model_protocols:
            raise HarnessProtocolError("model_protocols changed inside one replay")

    prior_types: set[str] = set()
    if attempt.last_seq == 0:
        if event_type != "run.started":
            raise HarnessProtocolError(
                "canonical attempt is missing run.started",
                code="missing_init",
            )
    elif event_type == "run.started":
        raise HarnessProtocolError("run.started appears more than once")

    # These checks are only needed around lifecycle boundaries.  Ordinary
    # message/tool deltas therefore take the attempt-lock + indexed receipt
    # path without scanning prior event JSON.
    boundary_types = set(HARNESS_TERMINAL_TYPES) | {"worker.finalization"}
    if event_type in HARNESS_TERMINAL_TYPES:
        prior_types = await _existing_event_types(
            db,
            attempt_id=attempt.attempt_id,
            event_types=HARNESS_TERMINAL_TYPES,
        )
        if prior_types:
            raise HarnessProtocolError("harness terminal appears more than once")
    elif event_type.startswith("delivery."):
        prior_types = await _existing_event_types(
            db,
            attempt_id=attempt.attempt_id,
            event_types=HARNESS_TERMINAL_TYPES,
        )
        if not prior_types:
            raise HarnessProtocolError("delivery event appears before harness terminal")
    elif event_type == "worker.finalization":
        prior_types = await _existing_event_types(
            db,
            attempt_id=attempt.attempt_id,
            event_types=boundary_types,
        )
        if not (prior_types & set(HARNESS_TERMINAL_TYPES)):
            raise HarnessProtocolError("worker.finalization appears before harness terminal")
        if "worker.finalization" in prior_types:
            raise HarnessProtocolError("worker.finalization appears more than once")
    elif event_type in TASK_TERMINAL_TYPES:
        prior_types = await _existing_event_types(
            db,
            attempt_id=attempt.attempt_id,
            event_types=boundary_types,
        )
        if not (prior_types & set(HARNESS_TERMINAL_TYPES)):
            raise HarnessProtocolError("task terminal appears before harness terminal")
        if "worker.finalization" not in prior_types:
            raise HarnessProtocolError("task terminal appears before worker.finalization")


async def ingest_canonical_event(
    db: AsyncSession,
    event: dict,
) -> EventIngestResult:
    """Accept one event exactly once, rejecting gaps and divergent duplicates."""
    normalized = validate_event_by_schema(event)
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

    event_ids = getattr(attempt, "_canonical_event_ids", None)
    if event_ids is None:
        event_ids = await _event_ids_for_attempt(
            db,
            attempt_id=attempt.attempt_id,
        )
        setattr(attempt, "_canonical_event_ids", event_ids)
    if normalized["event_id"] in event_ids:
        raise HarnessProtocolError(
            f"duplicate event_id: {normalized['event_id']}",
            code="duplicate_event",
        )

    await _validate_incremental_event_order(
        db,
        attempt=attempt,
        event=normalized,
    )
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
    event_ids.add(normalized["event_id"])
    if normalized["type"] == "worker.finalization":
        setattr(attempt, "_canonical_finalization_seen", True)
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
