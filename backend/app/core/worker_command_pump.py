"""V2 command dispatch pump: delivers queued commands to the in-flight Harness.

Implements the frozen command-plane delivery contract (open-harness-v2-schemas.md
§4 / phase1-design §2.2):

- A separate AsyncSession per cycle; each attempt is picked by a lease
  (``command_dispatch_owner``/``command_dispatch_expires_at``) under ``SKIP
  LOCKED`` so different attempts run in parallel while one dispatcher owns a
  given attempt.
- Commands are processed strictly in ``sequence_no`` order: a later command is
  never claimed before its earlier non-terminal predecessor has reached a
  terminal state (``delivered``/``rejected``).
- The actual send goes through a fixed in-image ``control_client.py`` via Docker
  exec (json on stdin). The transport is injectable for offline tests.
- On uncertainty the command is journaled to ``delivery_outcome_unknown`` (a
  rejection) rather than left ambiguous; terminals are never reopened.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_harness_commands import write_command_delivery, write_command_rejection
from app.core.utcnow import utcnow
from app.models import Task, TaskHarnessAttempt, TaskHarnessCommand, TaskStatus

logger = logging.getLogger(__name__)

# Control-transport command frame versions (schemas.md §4.3).
CONTROL_FRAME_VERSION = "1"

DEFAULT_LEASE_TTL_SECONDS = 120

# Result outcome strings returned by the fixed control_client transport.
DISPATCH_ACK = "ack"
DISPATCH_REJECT = "reject"
DISPATCH_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    status: str  # "delivered" | "rejected"
    rejection_code: str | None = None
    rejection_message: str | None = None


@dataclass(frozen=True, slots=True)
class PumpCycleResult:
    attempts_seen: int
    commands_processed: int
    commands_updated: int


CommandTransport = Callable[[dict, Any], Awaitable[dict]]


def _future(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


async def _claim_next_attempt(
    db: AsyncSession, *, owner: str, lease_ttl: int
) -> TaskHarnessAttempt | None:
    """Atomically lease one V2 attempt that still accepts commands.

    Uses ``SKIP LOCKED`` so concurrent dispatchers each claim a different
    attempt; an attempt is claimable when it has no unexpired lease or its
    lease expired (crash recovery). Only attempts whose control gate is
    ``accepting`` and whose task is RUNNING are eligible.
    """
    now = utcnow()
    stmt = (
        select(TaskHarnessAttempt)
        .join(Task, Task.id == TaskHarnessAttempt.task_id)
        .where(
            Task.status == TaskStatus.RUNNING,
            TaskHarnessAttempt.control_state == "accepting",
        )
        .where(
            (TaskHarnessAttempt.command_dispatch_expires_at.is_(None))
            | (TaskHarnessAttempt.command_dispatch_expires_at < now)
            | (TaskHarnessAttempt.command_dispatch_owner == owner)
        )
        .order_by(TaskHarnessAttempt.attempt_id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    attempt = (await db.execute(stmt)).scalars().first()
    if attempt is None:
        return None
    attempt.command_dispatch_owner = owner
    attempt.command_dispatch_expires_at = _future(lease_ttl)
    await db.flush()
    return attempt


async def _drop_lease(db: AsyncSession, attempt: TaskHarnessAttempt, *, owner: str) -> None:
    """Clear the lease only if we still own it."""
    await db.execute(
        update(TaskHarnessAttempt)
        .where(
            TaskHarnessAttempt.attempt_id == attempt.attempt_id,
            TaskHarnessAttempt.command_dispatch_owner == owner,
        )
        .values(command_dispatch_owner=None, command_dispatch_expires_at=None)
    )


async def _load_head_command(
    db: AsyncSession, attempt_id: str
) -> TaskHarnessCommand | None:
    """Load the lowest non-terminal command for the attempt (queue front)."""
    stmt = (
        select(TaskHarnessCommand)
        .where(
            TaskHarnessCommand.attempt_id == attempt_id,
            TaskHarnessCommand.status == "queued",
        )
        .order_by(TaskHarnessCommand.sequence_no.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def dispatch_one_command(
    db: AsyncSession,
    *,
    command: TaskHarnessCommand,
    attempt: TaskHarnessAttempt,
    transport: CommandTransport,
    owner: str,
) -> str:
    """Send one queued command and CAS it to a terminal state.

    Returns the final status ("delivered"/"rejected"). The transport is the only
    boundary to the in-image ``control_client.py``; it must return an outcome
    dict with ``status`` in {ack, reject, unknown} plus optional rejection fields.
    Any transport error is journaled as ``delivery_outcome_unknown``.
    """
    now = utcnow()
    frame = {
        "frame_version": CONTROL_FRAME_VERSION,
        "command_id": command.command_id,
        "task_id": command.task_id,
        "attempt_id": command.attempt_id,
        "sequence_no": command.sequence_no,
        "type": command.command_type,
        "payload": command.payload,
        "payload_digest": command.payload_digest,
        "control_gate": attempt.control_state,
        "dispatcher": owner,
    }
    try:
        outcome = await transport(frame, command=command, attempt=attempt)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Command %s dispatch transport error: %s; journaling delivery_outcome_unknown",
            command.command_id,
            exc,
        )
        await write_command_rejection(
            db,
            command_id=command.command_id,
            rejection_code="delivery_outcome_unknown",
            rejection_message="transport error during dispatch",
            rejected_at=now,
        )
        return "rejected"

    status = outcome.get("status")
    if status == DISPATCH_ACK:
        await write_command_delivery(db, command_id=command.command_id, delivered_at=now)
        return "delivered"
    if status == DISPATCH_REJECT:
        code = outcome.get("rejection_code") or "delivery_outcome_unknown"
        message = outcome.get("rejection_message") or "rejected by bridge"
        await write_command_rejection(
            db,
            command_id=command.command_id,
            rejection_code=code,
            rejection_message=message,
            rejected_at=now,
        )
        return "rejected"
    # Unknown / malformed outcome: do not leave the command ambiguous.
    await write_command_rejection(
        db,
        command_id=command.command_id,
        rejection_code="delivery_outcome_unknown",
        rejection_message=json.dumps(outcome, sort_keys=True)[:2000],
        rejected_at=now,
    )
    return "rejected"


async def run_pump_cycle(
    db: AsyncSession,
    *,
    owner: str,
    transport: CommandTransport,
    lease_ttl: int = DEFAULT_LEASE_TTL_SECONDS,
    max_commands_per_attempt: int = 8,
) -> PumpCycleResult:
    """Run one dispatch pass across the accepting V2 attempts.

    Claims at most one attempt per cycle (SKIP LOCKED), then processes its
    queue front strictly in sequence order, up to ``max_commands_per_attempt``
    commands before releasing the lease. In-flight tasks keep their lease; the
    caller is responsible for committing the session.
    """
    attempt = await _claim_next_attempt(db, owner=owner, lease_ttl=lease_ttl)
    if attempt is None:
        return PumpCycleResult(attempts_seen=0, commands_processed=0, commands_updated=0)

    processed = 0
    updated = 0
    for _ in range(max_commands_per_attempt):
        head = await _load_head_command(db, attempt.attempt_id)
        if head is None:
            break
        final_status = await dispatch_one_command(
            db,
            command=head,
            attempt=attempt,
            transport=transport,
            owner=owner,
        )
        processed += 1
        updated += 0 if final_status == "delivered" else 1  # rejected counts as an update
        await db.flush()
    # A delivered command leaves no more work; a rejected one also consumed the
    # head. The lease remains held while the attempt is still RUNNING so the
    # next cycle picks up the next head. We keep it owned and let the next
    # cycle re-claim under the same owner if not expired.
    return PumpCycleResult(
        attempts_seen=1,
        commands_processed=processed,
        commands_updated=updated,
    )
