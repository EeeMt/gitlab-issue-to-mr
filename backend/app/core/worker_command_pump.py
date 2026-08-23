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

import asyncio
import io
import json
import logging
import tarfile
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
CONTROL_CLIENT_PATH = "/tmp/codify-runtime/orchestration/worker-entrypoint/harness/control_client.py"
KIT_MANIFEST_PATH = "/opt/codify-kit/manifest.json"

# Result outcome strings returned by the fixed control_client transport.
DISPATCH_ACK = "ack"
DISPATCH_REJECT = "reject"
DISPATCH_UNKNOWN = "unknown"


def sys_executable() -> str:
    """Interpreter used inside the Worker container (python3 on PATH)."""
    return "python3"


def _async_session_local():
    from app.database import AsyncSessionLocal

    return AsyncSessionLocal()


async def run_pump_until_task_ends(
    task_id: int,
    *,
    session_factory,
    owner: str,
    interval_seconds: float = 2.0,
) -> int:
    """Drive the command pump while ``task_id`` is RUNNING (plan §4.7).

    The worker task thread launches this alongside container monitoring: each
    cycle claims an accepting attempt for this exact task, promotes a
    ``starting`` gate once the bridge answers its probe, and drains the queue
    front in strict order. Returns the number of commands processed.
    """
    processed = 0
    while True:
        async with session_factory() as db:
            still_running = await db.scalar(
                select(Task.status).where(Task.id == task_id)
            )
            if still_running != TaskStatus.RUNNING:
                break
            async def _task_scoped_transport(frame, command=None, attempt=None, **_kw):
                if attempt is None or attempt.task_id != task_id:
                    return {
                        "status": DISPATCH_UNKNOWN,
                        "rejection_code": "wrong_attempt",
                    }
                task = await db.get(Task, task_id)
                return await docker_exec_control_transport(
                    frame, attempt, task=task, db=db
                )

            try:
                cycle = await run_pump_cycle(
                    db, owner=owner, transport=_task_scoped_transport
                )
                await db.commit()
                processed += cycle.commands_processed
            except Exception:  # noqa: BLE001 - one bad cycle must not kill the pump
                logger.exception(
                    "Command pump cycle failed for task %s", task_id
                )
                await db.rollback()
        await asyncio.sleep(interval_seconds)
    return processed


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


async def _promote_starting_attempt(
    db: AsyncSession, *, owner: str, lease_ttl: int
) -> TaskHarnessAttempt | None:
    """Promote one ``starting`` attempt whose bridge is ready to ``accepting``.

    Probes the in-container bridge with a ``get_state`` control frame; an ACK
    proves the control endpoint is live, so the gate CASes ``starting ->
    accepting`` under the same attempt lease the dispatcher uses. Anything
    other than a clean ACK leaves the gate untouched (a later cycle retries;
    cancel/failure paths converge it to ``closed`` independently).
    """
    now = utcnow()
    stmt = (
        select(TaskHarnessAttempt)
        .join(Task, Task.id == TaskHarnessAttempt.task_id)
        .where(
            Task.status == TaskStatus.RUNNING,
            TaskHarnessAttempt.control_state == "starting",
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

    try:
        task = await db.get(Task, attempt.task_id)
        if task is None:
            return attempt
        outcome = await _probe_bridge(attempt, task, db=db)
    except Exception:  # noqa: BLE001 - transport probe must never crash the pump
        outcome = {"status": "unknown"}
    if outcome.get("status") == "ack":
        attempt.control_state = "accepting"
        await db.flush()
    else:
        logger.warning(
            "Gate probe for attempt %s: %s",
            attempt.attempt_id,
            outcome,
        )
    return attempt


async def _probe_bridge(attempt: TaskHarnessAttempt, task, db) -> dict:
    """Send one ``get_state`` frame through the docker-exec transport."""
    return await docker_exec_control_transport(
        {
            "frame_version": CONTROL_FRAME_VERSION,
            "control_gate": attempt.control_state,
            "type": "get_state",
        },
        attempt,
        task,
        db=db,
    )


async def docker_exec_control_transport(
    frame: dict, attempt: TaskHarnessAttempt, task=None, db: AsyncSession | None = None
) -> dict:
    """Run the fixed in-image control client for one frame via Docker exec.

    Resolves the attempt's RUNNING task container, pipes the frame JSON to
    ``control_client.py`` on stdin, and parses the outcome dict from stdout.
    Any failure maps to ``unknown`` — never an exception into the pump loop.
    """
    import asyncio

    from app.config import get_settings
    from app.core.worker_docker_targets import find_task_container

    settings = get_settings()
    if task is not None:
        try:
            _db, container, _connection = await find_task_container(
                db,
                task,
                settings,
                getattr(task, "container_id", None)
                or f"{settings.worker_container_prefix}-{task.id}-issue{task.issue_id}",
            )
        except Exception:  # noqa: BLE001 - unreachable/stopped container
            return {"status": DISPATCH_UNKNOWN, "rejection_code": "container_unreachable"}
        if container is None:
            return {"status": DISPATCH_UNKNOWN, "rejection_code": "container_missing"}

        def _exec() -> dict:
            # Remote-daemon safe: pass the frame as a file argument instead of
            # stdin (exec sockets over TCP are HTTP-framed and unusable).
            import shlex

            frame_path = "/tmp/codify-runtime/control-frame.json"
            payload = json.dumps(frame).encode()
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
                info = tarfile.TarInfo(name="control-frame.json")
                info.size = len(payload)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(payload))
            container.put_archive(
                "/tmp/codify-runtime", tar_buffer.getvalue()
            )

            def _read(path: str) -> bytes:
                probe = container.client.api.exec_create(
                    container.id, ["cat", path], stdout=True
                )
                out = container.client.api.exec_start(probe["Id"])
                if isinstance(out, bytes):
                    return out
                return b"".join(out)

            try:
                kit_manifest = json.loads(_read(KIT_MANIFEST_PATH))
                bash_bin = str(kit_manifest.get("bash") or "")
                runtime_bin = str(kit_manifest.get("runtime_bin") or "")
            except Exception:  # noqa: BLE001 - fall back below
                bash_bin, runtime_bin = "", ""
            if not bash_bin or not runtime_bin:
                return {
                    "status": DISPATCH_UNKNOWN,
                    "rejection_code": "delivery_outcome_unknown",
                    "rejection_message": "kit runtime unavailable in container",
                }
            outcome_path = "/tmp/codify-runtime/control-outcome.json"
            command = [
                bash_bin,
                "-c",
                f'exec "{runtime_bin}/python3" "{CONTROL_CLIENT_PATH}" '
                f'< {shlex.quote(frame_path)} > {shlex.quote(outcome_path)} 2>&1',
            ]
            run = container.client.api.exec_create(
                container.id,
                command,
                stdout=True,
                stderr=True,
            )
            container.client.api.exec_start(run["Id"])
            result = container.client.api.exec_create(
                container.id,
                ["cat", outcome_path],
                stdout=True,
            )
            output = container.client.api.exec_start(result["Id"])
            if not isinstance(output, bytes):
                output = b"".join(output)
            try:
                return json.loads(output.decode(errors="replace").strip().splitlines()[-1])
            except (ValueError, IndexError):
                return {
                    "status": DISPATCH_UNKNOWN,
                    "rejection_code": "delivery_outcome_unknown",
                    "rejection_message": f"unparseable control client output: {output[:200]}",
                }

        try:
            return await asyncio.to_thread(_exec)
        except Exception as exc:  # noqa: BLE001 - transport errors are outcomes
            logger.warning("Control transport error: %s", exc)
            return {
                "status": DISPATCH_UNKNOWN,
                "rejection_code": "delivery_outcome_unknown",
                "rejection_message": str(exc)[:500],
            }



async def _record_control_event(
    db: AsyncSession, *, task_id: int, event_type: str, payload: dict
) -> None:
    """Project a control-plane audit event into the product-visible log.

    Mirrors the projector's ``control_event`` TaskLog rows so the event
    stream shows delivered/rejected alongside the DB status (plan §6.2).
    Never touches task_harness_commands rows.
    """
    from app.models import TaskLog

    db.add(
        TaskLog(
            task_id=task_id,
            log_level="INFO",
            message="",
            log_type="control_event",
            log_metadata=json.dumps(
                {"type": event_type, **payload}, ensure_ascii=False
            ),
        )
    )


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
        await _record_control_event(
            db,
            task_id=command.task_id,
            event_type="control.command.delivered",
            payload={
                "command_id": command.command_id,
                "payload_digest": command.payload_digest,
                "sequence_no": command.sequence_no,
                "delivered_at": now.isoformat(),
            },
        )
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
        await _record_control_event(
            db,
            task_id=command.task_id,
            event_type="control.command.rejected",
            payload={
                "command_id": command.command_id,
                "payload_digest": command.payload_digest,
                "sequence_no": command.sequence_no,
                "rejection_code": code,
                "rejection_message": message,
            },
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
        # Plan §4.7: command-capable attempts open in `starting`; once the
        # bridge control endpoint answers a get_state probe the pump promotes
        # the gate to `accepting` so queued commands become deliverable.
        attempt = await _promote_starting_attempt(db, owner=owner, lease_ttl=lease_ttl)
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
