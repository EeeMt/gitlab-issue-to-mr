"""Transactional V2 harness command creation and delivery primitives.

Implements the frozen command contract (open-harness-v2-schemas.md §4):
client-id idempotency, canonical payload digest, attempt-scoped strict
sequence allocation under the attempt row lock, and CAS ``queued ->
delivered|rejected`` written only by the command pump. Terminal states are
immutable; the projector never writes back to these rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA_V2,
    HARNESS_CONTRACT_VERSION_V2,
)
from app.core.harness_protocol import (
    command_payload_digest as canonical_digest,
)
from app.core.harness_registry import HarnessRegistryError, registry_catalog_from_manifest
from app.core.utcnow import utcnow
from app.models import (
    Task,
    TaskHarnessAttempt,
    TaskHarnessCommand,
    TaskStatus,
)


class CommandError(ValueError):
    """A command could not be created or terminalized."""

    def __init__(self, message: str, *, code: str = "command_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CommandCreateResult:
    command_id: str
    sequence_no: int
    created: bool
    # One of: "created", "existing_same", "existing_conflict", or a rejection
    # code (deterministic, no queued row created).
    outcome: str
    rejection_code: str | None = None
    rejection_message: str | None = None


def bundle_supports_command(
    bundle: object | None, harness_key: str, command_type: str
) -> bool:
    """Read command eligibility from the task's immutable V2 manifest.

    This is intentionally the same safe projection used by the catalog API:
    neither a harness key supplied by the client nor today's source checkout
    can upgrade a historical task's control capability.  Any malformed,
    legacy, or incomplete bundle is not command-capable.
    """
    if command_type not in {"steer", "follow_up"}:
        return False
    if getattr(bundle, "contract_version", None) != HARNESS_CONTRACT_VERSION_V2:
        return False
    manifest = getattr(bundle, "manifest", None)
    if not isinstance(manifest, dict):
        return False
    try:
        catalog = registry_catalog_from_manifest(manifest)
    except (HarnessRegistryError, ValueError, TypeError):
        return False
    adapter = next((entry for entry in catalog if entry["key"] == harness_key), None)
    if adapter is None:
        return False
    capability_name = "steering" if command_type == "steer" else "follow_up"
    return adapter["capabilities"].get(capability_name) is True


async def _load_current_attempt(
    db: AsyncSession, *, task_id: int, for_update: bool
) -> TaskHarnessAttempt | None:
    stmt = (
        select(TaskHarnessAttempt)
        .where(TaskHarnessAttempt.task_id == task_id)
        .order_by(TaskHarnessAttempt.attempt_no.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_command(
    db: AsyncSession,
    *,
    task_id: int,
    command_id: str,
    command_type: str,
    payload: dict,
    created_by: str,
) -> CommandCreateResult:
    """Create a queued command for the running V2 attempt, or reject.

    Idempotency is checked first (per schemas.md §4): an existing command_id
    with the same digest returns the existing row; a different digest is 409.
    Only new IDs proceed to eligibility checks (RUNNING, exact V2 attempt,
    harness capability, ``control_state=accepting``).
    """
    if command_type not in {"steer", "follow_up"}:
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="invalid_command_type",
            rejection_code="invalid_command_type",
            rejection_message="type must be steer or follow_up",
        )
    text = payload.get("text")
    if not isinstance(text, str):
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="invalid_command_type",
            rejection_code="invalid_command_type",
            rejection_message="payload.text must be a string",
        )
    if len(text) > 4000:
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="payload_too_large",
            rejection_code="payload_too_large",
            rejection_message="payload.text exceeds the 4000-char limit",
        )

    existing = await db.get(TaskHarnessCommand, command_id)
    if existing is not None:
        digest = canonical_digest(task_id, existing.attempt_id, command_type, payload)
        if existing.payload_digest == digest:
            return CommandCreateResult(
                command_id=command_id,
                sequence_no=existing.sequence_no,
                created=False,
                outcome="existing_same",
            )
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="existing_conflict",
            rejection_code="existing_conflict",
            rejection_message="command_id already exists with a different payload",
        )

    task = (
        await db.execute(
            select(Task)
            .options(selectinload(Task.runtime_bundle))
            .where(Task.id == task_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise CommandError("unknown task", code="task_not_found")
    if task.status != TaskStatus.RUNNING:
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="task_not_running",
            rejection_code="task_not_running",
            rejection_message="task is not RUNNING",
        )

    attempt = await _load_current_attempt(db, task_id=task_id, for_update=True)
    if attempt is None:
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="task_not_running",
            rejection_code="task_not_running",
            rejection_message="no running Harness attempt",
        )
    if attempt.event_schema != CANONICAL_EVENT_SCHEMA_V2:
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="attempt_mismatch",
            rejection_code="attempt_mismatch",
            rejection_message="attempt is not an exact V2 attempt",
        )
    if not bundle_supports_command(task.runtime_bundle, attempt.harness_key, command_type):
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="unsupported_harness",
            rejection_code="unsupported_harness",
            rejection_message=(
                f"frozen Runtime Bundle harness {attempt.harness_key} does not support "
                f"{command_type}"
            ),
        )
    if attempt.control_state != "accepting":
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="control_gate_closed",
            rejection_code="control_gate_closed",
            rejection_message=f"control gate is {attempt.control_state}, not accepting",
        )

    sequence_no = attempt.next_command_sequence
    digest = canonical_digest(task_id, attempt.attempt_id, command_type, payload)
    db.add(
        TaskHarnessCommand(
            command_id=command_id,
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            sequence_no=sequence_no,
            command_type=command_type,
            payload=dict(payload),
            payload_digest=digest,
            status="queued",
            created_by=created_by,
            created_at=utcnow(),
            delivery_attempts=0,
        )
    )
    attempt.next_command_sequence = sequence_no + 1
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent caller committed the same command_id between our
        # existence check and this flush (schemas.md §4 requires handling the
        # unique-key race by re-reading and re-judging). Roll back and resolve
        # against the committed row instead of surfacing a 500.
        await db.rollback()
        raced = await db.get(TaskHarnessCommand, command_id)
        if raced is not None and raced.payload_digest == digest:
            return CommandCreateResult(
                command_id=command_id,
                sequence_no=raced.sequence_no,
                created=False,
                outcome="existing_same",
            )
        return CommandCreateResult(
            command_id=command_id,
            sequence_no=0,
            created=False,
            outcome="existing_conflict",
            rejection_code="existing_conflict",
            rejection_message="command_id already exists with a different payload",
        )
    return CommandCreateResult(
        command_id=command_id,
        sequence_no=sequence_no,
        created=True,
        outcome="created",
    )


async def write_command_delivery(
    db: AsyncSession, *, command_id: str, delivered_at: datetime
) -> bool:
    """CAS ``queued -> delivered`` (pump only). Ignores non-queued rows."""
    command = (
        await db.execute(
            select(TaskHarnessCommand)
            .where(TaskHarnessCommand.command_id == command_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if command is None or command.status != "queued":
        return False
    command.status = "delivered"
    command.delivered_at = delivered_at
    command.delivery_attempts += 1
    command.last_attempt_at = delivered_at
    await db.flush()
    return True


async def write_command_rejection(
    db: AsyncSession,
    *,
    command_id: str,
    rejection_code: str,
    rejection_message: str,
    rejected_at: datetime,
) -> bool:
    """CAS ``queued -> rejected`` (pump only). Ignores non-queued rows."""
    command = (
        await db.execute(
            select(TaskHarnessCommand)
            .where(TaskHarnessCommand.command_id == command_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if command is None or command.status != "queued":
        return False
    command.status = "rejected"
    command.rejected_at = rejected_at
    command.rejection_code = rejection_code
    command.rejection_message = rejection_message
    command.delivery_attempts += 1
    command.last_attempt_at = rejected_at
    await db.flush()
    return True


async def list_commands(
    db: AsyncSession, *, task_id: int
) -> list[TaskHarnessCommand]:
    """Return a task's commands ordered by attempt/sequence for recovery."""
    return list(
        (
            await db.execute(
                select(TaskHarnessCommand)
                .where(TaskHarnessCommand.task_id == task_id)
                .order_by(TaskHarnessCommand.attempt_id, TaskHarnessCommand.sequence_no)
            )
        ).scalars()
    )
