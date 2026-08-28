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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_harness_commands import (
    begin_command_dispatch,
    mark_command_native_sent,
    requeue_pre_send_failure,
    write_command_delivery,
    write_command_outcome_unknown,
    write_command_rejection,
)
from app.core.utcnow import utcnow
from app.models import Task, TaskHarnessAttempt, TaskHarnessCommand, TaskStatus

logger = logging.getLogger(__name__)

# Control-transport command frame versions (schemas.md §4.3).
CONTROL_FRAME_VERSION = "1"

DEFAULT_LEASE_TTL_SECONDS = 120
# A Docker exec used for a control probe/close must never pin the scheduler
# pump indefinitely.  The in-container client has its own 16s Unix-socket
# timeout; this outer bound also covers a remote Docker API that stops
# returning from put_archive/exec_start.
CONTROL_TRANSPORT_TIMEOUT_SECONDS = 30
CONTROL_RESULT_POLL_INTERVAL_SECONDS = 0.1
CONTROL_RESULT_TIMEOUT_SECONDS = 20

# Result outcome strings returned by the fixed control_client transport.
CONTROL_CLIENT_PATH = (
    "/tmp/codify-runtime/orchestration/worker-entrypoint/harness/control_client.py"
)
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
    startup_timeout_seconds: float = 300.0,
) -> int:
    """Drive the command pump from scheduler handoff until task termination.

    The worker task thread launches this alongside container monitoring: each
    cycle claims an accepting attempt for this exact task, promotes a
    ``starting`` gate once the bridge answers its probe, and drains the queue
    front in strict order. Returns the number of commands processed.
    """
    processed = 0
    startup_deadline = asyncio.get_running_loop().time() + startup_timeout_seconds
    while True:
        async with session_factory() as db:
            status = await db.scalar(select(Task.status).where(Task.id == task_id))
            if status is None or status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                break
            if status in {TaskStatus.PENDING, TaskStatus.QUEUED}:
                # Scheduler starts the task thread before WorkerExecutor's
                # causal RUNNING commit.  Remain owned/cancellable across that
                # handoff rather than exiting forever on the first QUEUED read.
                if asyncio.get_running_loop().time() >= startup_deadline:
                    logger.warning("Command pump startup timed out for task %s", task_id)
                    break
                pass
            elif status != TaskStatus.RUNNING:
                break
            else:
                async def _task_scoped_transport(frame, command=None, attempt=None, **_kw):
                    if (
                        frame.get("task_id") != task_id
                        or attempt is None
                        or attempt.task_id != task_id
                    ):
                        return {
                            "status": DISPATCH_UNKNOWN,
                            "rejection_code": "wrong_attempt",
                        }
                    task = await db.get(Task, task_id)
                    return await docker_exec_control_transport(frame, attempt, task=task, db=db)

                try:
                    cycle = await run_pump_cycle(
                        db,
                        task_id=task_id,
                        owner=owner,
                        transport=_task_scoped_transport,
                    )
                    await db.commit()
                    processed += cycle.commands_processed
                except Exception:  # noqa: BLE001 - one bad cycle must not kill the pump
                    logger.exception("Command pump cycle failed for task %s", task_id)
                    await db.rollback()
        # Do not retain a database connection while waiting for WorkerExecutor
        # to cross the causal QUEUED/PENDING -> RUNNING edge.
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
    db: AsyncSession, *, task_id: int, owner: str, lease_ttl: int
) -> TaskHarnessAttempt | None:
    """Atomically lease one V2 attempt that needs a pump pass.

    Uses ``SKIP LOCKED`` so concurrent dispatchers each claim a different
    attempt; an attempt is claimable when it has no unexpired lease or its
    lease expired (crash recovery). Only attempts whose control gate is
    ``accepting``/``closing`` and whose task is RUNNING are eligible. An
    accepting attempt must have queued work; a drained closing attempt is
    claimable only when it is not waiting for the native follow-up turn, so
    the pump can complete its owner close handshake. A closing attempt with
    queued work remains claimable regardless of that handshake state. This
    keeps idle attempts from starving newer work while still allowing a
    pre-drained closing attempt to converge to ``closed``.
    """
    now = utcnow()
    stmt = (
        select(TaskHarnessAttempt)
        .join(Task, Task.id == TaskHarnessAttempt.task_id)
        .where(
            Task.id == task_id,
            TaskHarnessAttempt.task_id == task_id,
            Task.status == TaskStatus.RUNNING,
            TaskHarnessAttempt.control_state.in_(("accepting", "closing")),
            exists(
                select(1).where(
                    TaskHarnessCommand.attempt_id == TaskHarnessAttempt.attempt_id,
                    TaskHarnessCommand.task_id == task_id,
                    TaskHarnessCommand.status.in_(("queued", "dispatching")),
                )
            )
            | (
                (TaskHarnessAttempt.control_state == "closing")
                & TaskHarnessAttempt.awaiting_follow_up_turn.is_(False)
            ),
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
    db: AsyncSession, *, task_id: int, owner: str, lease_ttl: int
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
            Task.id == task_id,
            TaskHarnessAttempt.task_id == task_id,
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
        task = await db.get(Task, task_id)
        if task is None:
            return attempt
        if attempt.task_id != task_id:
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
            "task_id": task.id,
            "attempt_id": attempt.attempt_id,
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
    ``control_client.py`` via a detached Docker exec, then reads its
    correlated outcome file from the container.  Detaching the client is
    important for the close path: the owner may acknowledge the drain marker
    and exit the container while the Docker API is still holding the exec
    response open.
    Any failure maps to ``unknown`` — never an exception into the pump loop.
    """
    import asyncio

    from app.config import get_settings
    from app.core.worker_docker_targets import find_task_container

    settings = get_settings()
    if task is not None:
        try:
            # ``find_task_container`` includes credential negotiation and a
            # Docker API lookup; bound that remote operation as well as the
            # in-container exec below.
            _db, container, _connection = await asyncio.wait_for(
                find_task_container(
                    db,
                    task,
                    settings,
                    getattr(task, "container_id", None)
                    or f"{settings.worker_container_prefix}-{task.id}-issue{task.issue_id}",
                ),
                timeout=CONTROL_TRANSPORT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("Control container lookup timed out for task %s", task.id)
            return {
                "status": DISPATCH_UNKNOWN,
                "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "control container lookup timed out",
            }
        except Exception:  # noqa: BLE001 - unreachable/stopped container
            return {"status": DISPATCH_UNKNOWN, "rejection_code": "container_unreachable"}
        if container is None:
            return {"status": DISPATCH_UNKNOWN, "rejection_code": "container_missing"}

        def _exec() -> dict:
            # Remote-daemon safe: pass the frame as a file argument instead of
            # stdin (exec sockets over TCP are HTTP-framed and unusable).
            import shlex

            frame_path = "/tmp/codify-runtime/control-frame.json"
            # The outcome file survives between control calls.  Correlate every
            # detached invocation so a stale probe/close result can never be
            # mistaken for the current request.
            control_request_id = uuid.uuid4().hex
            control_frame = dict(frame)
            control_frame["control_request_id"] = control_request_id
            payload = json.dumps(control_frame).encode()
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
                info = tarfile.TarInfo(name="control-frame.json")
                info.size = len(payload)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(payload))
            container.put_archive("/tmp/codify-runtime", tar_buffer.getvalue())

            def _read(path: str) -> bytes:
                probe = container.client.api.exec_create(container.id, ["cat", path], stdout=True)
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
                f"< {shlex.quote(frame_path)} > {shlex.quote(outcome_path)} 2>&1",
            ]
            run = container.client.api.exec_create(
                container.id,
                command,
                stdout=True,
                stderr=True,
            )
            # Do not wait synchronously on the control client.  In particular,
            # a close ACK sets the owner's local drain event, which can stop the
            # Worker container before a non-detached exec response is released
            # by a remote Docker daemon.
            container.client.api.exec_start(run["Id"], detach=True)

            def _read_archive(path: str) -> bytes:
                bits, _stat = container.get_archive(path)
                archive_bytes = bits if isinstance(bits, bytes) else b"".join(bits)
                with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
                    member = next((item for item in archive.getmembers() if item.isfile()), None)
                    if member is None:
                        return b""
                    stream = archive.extractfile(member)
                    return stream.read() if stream is not None else b""

            deadline = time.monotonic() + CONTROL_RESULT_TIMEOUT_SECONDS
            while True:
                try:
                    output = _read_archive(outcome_path)
                    lines = output.decode(errors="replace").strip().splitlines()
                    result = json.loads(lines[-1]) if lines else None
                except Exception:  # noqa: BLE001 - file races while exec starts/exits
                    result = None
                if (
                    isinstance(result, dict)
                    and result.get("control_request_id") == control_request_id
                ):
                    return result

                # A detached exec that has already exited will not produce a
                # newer result.  Inspect only after the first archive read so a
                # fast close still gets one last chance to publish its outcome.
                try:
                    state = container.client.api.exec_inspect(run["Id"])
                except Exception:  # noqa: BLE001 - keep polling on old daemons
                    state = None
                if isinstance(state, dict) and state.get("Running") is False:
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(CONTROL_RESULT_POLL_INTERVAL_SECONDS)

            return {
                "status": DISPATCH_UNKNOWN,
                "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "control client produced no correlated outcome",
            }

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_exec),
                timeout=CONTROL_TRANSPORT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("Control transport timed out for task %s", task.id)
            return {
                "status": DISPATCH_UNKNOWN,
                "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "control transport timed out",
            }
        except Exception as exc:  # noqa: BLE001 - transport errors are outcomes
            logger.warning("Control transport failed with %s", type(exc).__name__)
            return {
                "status": DISPATCH_UNKNOWN,
                "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "control transport failed",
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
            log_metadata=json.dumps({"type": event_type, **payload}, ensure_ascii=False),
        )
    )


async def _drop_lease(
    db: AsyncSession, *, task_id: int, attempt: TaskHarnessAttempt, owner: str
) -> None:
    """Clear the lease only if we still own the same Task-scoped attempt."""
    await db.execute(
        update(TaskHarnessAttempt)
        .where(
            TaskHarnessAttempt.attempt_id == attempt.attempt_id,
            TaskHarnessAttempt.task_id == task_id,
            TaskHarnessAttempt.command_dispatch_owner == owner,
        )
        .values(command_dispatch_owner=None, command_dispatch_expires_at=None)
    )


async def _load_head_command(
    db: AsyncSession, *, task_id: int, attempt_id: str
) -> TaskHarnessCommand | None:
    """Load the queue front only inside the owning Task and attempt."""
    stmt = (
        select(TaskHarnessCommand)
        .join(
            TaskHarnessAttempt,
            TaskHarnessAttempt.attempt_id == TaskHarnessCommand.attempt_id,
        )
        .where(
            TaskHarnessCommand.task_id == task_id,
            TaskHarnessAttempt.task_id == task_id,
            TaskHarnessAttempt.attempt_id == attempt_id,
            TaskHarnessCommand.attempt_id == attempt_id,
            TaskHarnessCommand.status.in_(("queued", "dispatching")),
        )
        .order_by(TaskHarnessCommand.sequence_no.asc())
        .limit(1)
        # The queue front is ordered state, not a work-stealing candidate.
        # Waiting for a locked lower sequence is required; SKIP LOCKED could
        # incorrectly expose a later command while its predecessor is in flux.
        .with_for_update(of=TaskHarnessCommand)
    )
    return (await db.execute(stmt)).scalars().first()


async def _recover_dispatching_head(db: AsyncSession, *, command: TaskHarnessCommand) -> bool:
    """Fail closed after a dispatcher/owner restart.

    A durable ``dispatching`` row is proof that the old owner crossed the
    commit-before-send boundary.  We cannot establish whether Pi accepted the
    bytes, therefore it is terminalized as unknown and is never re-injected.
    """
    if command.status != "dispatching":
        return False
    return await write_command_outcome_unknown(
        db,
        command_id=command.command_id,
        message="dispatcher recovery cannot prove native send outcome",
        occurred_at=utcnow(),
    )


async def _record_unknown_outcome(db: AsyncSession, command: TaskHarnessCommand) -> None:
    """Audit ambiguity without retaining command text or transport errors."""
    await _record_control_event(
        db,
        task_id=command.task_id,
        event_type="control.command.outcome_unknown",
        payload={
            "command_id": command.command_id,
            "payload_digest": command.payload_digest,
            "sequence_no": command.sequence_no,
            "code": "delivery_outcome_unknown",
        },
    )


async def _close_drained_attempt(
    *, db: AsyncSession, task_id: int, attempt: TaskHarnessAttempt, transport: CommandTransport
) -> bool:
    """Ask the sole Pi owner to end only after its backend queue drained.

    The IPC ACK is the final causal edge: without it we leave the database gate
    in ``closing`` so a later pump can retry safely instead of finalizing the
    worker while the owner is still able to accept an already-admitted command.
    """
    if attempt.task_id != task_id:
        raise ValueError("close transport task scope does not match attempt")
    outcome = await transport(
        {
            "frame_version": CONTROL_FRAME_VERSION,
            "task_id": task_id,
            "attempt_id": attempt.attempt_id,
            "type": "close",
            "control_gate": "closing",
        },
        attempt=attempt,
    )
    if outcome.get("status") != DISPATCH_ACK:
        return False
    attempt.control_state = "closed"
    attempt.force_close_requested = False
    await db.flush()
    return True


async def dispatch_one_command(
    db: AsyncSession,
    *,
    task_id: int,
    command: TaskHarnessCommand,
    attempt: TaskHarnessAttempt,
    transport: CommandTransport,
    owner: str,
) -> str:
    """Send one queued command and CAS it to a terminal state.

    Returns the final status. The transport is the only
    boundary to the in-image ``control_client.py``; it must return an outcome
    dict with ``status`` in {ack, reject, unknown} plus optional rejection fields.
    Any transport error is journaled as ``delivery_outcome_unknown``.
    """
    if (
        command.task_id != task_id
        or attempt.task_id != task_id
        or command.attempt_id != attempt.attempt_id
    ):
        raise ValueError("command, attempt, and pump task scope do not match")
    now = utcnow()
    native_request_id = str(1_000_000 + command.sequence_no)
    if command.command_type == "follow_up" and attempt.control_state == "closing":
        armed = await db.execute(
            update(TaskHarnessAttempt)
            .where(
                TaskHarnessAttempt.attempt_id == attempt.attempt_id,
                TaskHarnessAttempt.control_state == "closing",
                TaskHarnessAttempt.awaiting_follow_up_turn.is_(False),
                TaskHarnessAttempt.task_id == Task.id,
                Task.status == TaskStatus.RUNNING,
            )
            .values(
                awaiting_follow_up_turn=True,
                pending_follow_up_command_id=command.command_id,
                pending_follow_up_native_id=native_request_id,
            )
        )
        if not armed.rowcount:
            return "terminalized"
        attempt.awaiting_follow_up_turn = True
        attempt.pending_follow_up_command_id = command.command_id
        attempt.pending_follow_up_native_id = native_request_id
    claimed = await begin_command_dispatch(db, command_id=command.command_id, started_at=now)
    if claimed is None:
        return command.status
    # This is the critical crash boundary.  Persist it before Docker exec so a
    # new pump sees ``dispatching`` and fails closed instead of duplicating Pi.
    await db.commit()
    frame = {
        "frame_version": CONTROL_FRAME_VERSION,
        "command_id": command.command_id,
        "task_id": task_id,
        "attempt_id": command.attempt_id,
        "sequence_no": command.sequence_no,
        "type": command.command_type,
        "payload": command.payload,
        "payload_digest": command.payload_digest,
        "control_gate": attempt.control_state,
        "dispatcher": owner,
        "native_request_id": native_request_id,
    }
    try:
        outcome = await transport(frame, command=claimed, attempt=attempt)
    except Exception:  # noqa: BLE001
        # A transport exception has no trustworthy pre-send proof.  Docker exec
        # may have entered the control client, so fail closed rather than replay.
        await write_command_outcome_unknown(
            db,
            command_id=command.command_id,
            message="transport exited before reporting dispatch outcome",
            occurred_at=utcnow(),
        )
        await _record_unknown_outcome(db, command)
        if command.command_type == "follow_up":
            await _fail_pending_follow_up(db, attempt, command.command_id, "follow-up transport outcome unknown")
        return "outcome_unknown"

    status = outcome.get("status")
    returned_native_id = outcome.get("native_request_id") or outcome.get("native_id")
    if outcome.get("native_sent"):
        sent = await mark_command_native_sent(
            db,
            command_id=command.command_id,
            native_request_id=str(returned_native_id) if returned_native_id is not None else None,
            sent_at=utcnow(),
        )
        if not sent:
            # Cancellation/terminalization won the race.  Do not resurrect a
            # terminal command with a late native ACK.
            return "terminalized"
    if status == DISPATCH_ACK:
        delivered = await write_command_delivery(db, command_id=command.command_id, delivered_at=now)
        if not delivered:
            return "terminalized"
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
        # Transport text is untrusted (it can contain command/endpoint data).
        message = "control command rejected by Pi owner"
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
        if command.command_type == "follow_up":
            await _clear_pending_follow_up(db, attempt, command.command_id)
        return "rejected"
    if status == "retry":
        await requeue_pre_send_failure(db, command_id=command.command_id)
        if command.command_type == "follow_up":
            await _clear_pending_follow_up(db, attempt, command.command_id)
        return "queued"
    # Unknown / malformed outcome after a bridge response is ambiguous.  Do
    # not coerce it to ``rejected``: it must remain visibly distinct in audit
    # and must never be re-sent on recovery.
    await write_command_outcome_unknown(
        db,
        command_id=command.command_id,
        message="control transport returned an unrecognized outcome",
        occurred_at=now,
    )
    await _record_unknown_outcome(db, command)
    if command.command_type == "follow_up":
        await _fail_pending_follow_up(db, attempt, command.command_id, "follow-up delivery outcome unknown")
    return "outcome_unknown"


async def _clear_pending_follow_up(db: AsyncSession, attempt: TaskHarnessAttempt, command_id: str) -> None:
    await db.execute(
        update(TaskHarnessAttempt)
        .where(
            TaskHarnessAttempt.attempt_id == attempt.attempt_id,
            TaskHarnessAttempt.pending_follow_up_command_id == command_id,
        )
        .values(
            awaiting_follow_up_turn=False,
            pending_follow_up_command_id=None,
            pending_follow_up_native_id=None,
        )
    )
    attempt.awaiting_follow_up_turn = False
    attempt.pending_follow_up_command_id = None
    attempt.pending_follow_up_native_id = None


async def _fail_pending_follow_up(db: AsyncSession, attempt: TaskHarnessAttempt, command_id: str, reason: str) -> None:
    """Fail closed once a continuation may have reached Pi."""
    from app.core.task_command_gate import request_force_close_after_unknown_follow_up

    await request_force_close_after_unknown_follow_up(
        db,
        attempt=attempt,
        command_id=command_id,
        native_id=attempt.pending_follow_up_native_id,
        reason=reason,
    )


async def run_pump_cycle(
    db: AsyncSession,
    *,
    task_id: int,
    owner: str,
    transport: CommandTransport,
    lease_ttl: int = DEFAULT_LEASE_TTL_SECONDS,
    max_commands_per_attempt: int = 8,
) -> PumpCycleResult:
    """Run one dispatch pass for the requested Task's accepting V2 attempt.

    Claims at most one attempt per cycle (SKIP LOCKED), then processes its
    queue front strictly in sequence order, up to ``max_commands_per_attempt``
    commands before releasing the lease. In-flight tasks keep their lease; the
    caller is responsible for committing the session.
    """
    attempt = await _claim_next_attempt(
        db, task_id=task_id, owner=owner, lease_ttl=lease_ttl
    )
    if attempt is None:
        # Plan §4.7: command-capable attempts open in `starting`; once the
        # bridge control endpoint answers a get_state probe the pump promotes
        # the gate to `accepting` so queued commands become deliverable.
        attempt = await _promote_starting_attempt(
            db, task_id=task_id, owner=owner, lease_ttl=lease_ttl
        )
    if attempt is None:
        return PumpCycleResult(attempts_seen=0, commands_processed=0, commands_updated=0)

    processed = 0
    updated = 0
    for _ in range(max_commands_per_attempt):
        head = await _load_head_command(
            db, task_id=task_id, attempt_id=attempt.attempt_id
        )
        if head is None:
            break
        if head.status == "dispatching":
            # A previous owner died after its durable claim.  This is an
            # explicit exactly-once boundary: fail closed, then allow only the
            # following queue item on a future cycle.
            await _recover_dispatching_head(db, command=head)
            await _record_unknown_outcome(db, head)
            if head.command_type == "follow_up":
                await _fail_pending_follow_up(
                    db, attempt, head.command_id, "dispatcher recovery cannot prove follow-up delivery"
                )
            processed += 1
            updated += 1
            break
        final_status = await dispatch_one_command(
            db,
            task_id=task_id,
            command=head,
            attempt=attempt,
            transport=transport,
            owner=owner,
        )
        processed += 1
        updated += 0 if final_status in {"delivered", "queued"} else 1
        await db.flush()
        if final_status == "queued":
            # Pre-send retry keeps this exact head in place; do not spin it.
            break
    if attempt.control_state == "closing":
        remaining = await _load_head_command(
            db, task_id=task_id, attempt_id=attempt.attempt_id
        )
        if remaining is None and not attempt.awaiting_follow_up_turn:
            # All commands admitted before the settled transition drained in
            # sequence; new PUTs are rejected by the closing gate.
            try:
                await _close_drained_attempt(
                    db=db, task_id=task_id, attempt=attempt, transport=transport
                )
            except Exception:  # noqa: BLE001 - leave closing for a safe retry
                logger.warning("Pi owner close IPC failed for attempt %s", attempt.attempt_id)
    # A delivered command leaves no more work; a rejected one also consumed the
    # head. The lease remains held while the attempt is still RUNNING so the
    # next cycle picks up the next head. We keep it owned and let the next
    # cycle re-claim under the same owner if not expired.
    return PumpCycleResult(
        attempts_seen=1,
        commands_processed=processed,
        commands_updated=updated,
    )
