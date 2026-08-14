"""Issue input-stream ordering domain service.

Enforces the Issue task ordering model: ``issue_sequence`` is the immutable
turn number within an Issue and the single source of truth for execution order.
All writers allocate through ``append_task_issue_context`` inside the Issue row
lock; the Scheduler only promotes the active queue head and claims it atomically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.utcnow import utcnow
from app.core.worker_runtime_readiness import read_runtime_readiness
from app.models import IssueExecutionLock, Task, TaskStatus

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
ACTIVE_STATUS_VALUES = [s.value for s in ACTIVE_STATUSES]
TERMINAL_STATUS_VALUES = ["completed", "failed", "cancelled"]

# Schedule window conflict envelope (FastAPI HTTPException(detail=dict)).
SCHEDULE_CONFLICT_CODE = "issue_schedule_order_conflict"
SEQUENCE_REPAIR_CODE = "issue_sequence_repair_required"
LINEAGE_CONFLICT_CODE = "issue_lineage_conflict"


class IssueOrderIntegrityError(Exception):
    """Fail-closed signal: an Issue's sequence/lineage cannot be trusted."""

    def __init__(self, issue_id: int, reason: str) -> None:
        self.issue_id = issue_id
        self.reason = reason
        self.detail: dict[str, Any] = {
            "code": SEQUENCE_REPAIR_CODE,
            "message": "Issue task sequence integrity requires manual repair",
            "issue_id": issue_id,
            "reason": reason,
        }
        super().__init__(f"{SEQUENCE_REPAIR_CODE}:{issue_id}:{reason}")


class ScheduleWindowConflict(Exception):
    """Structured 409 for a scheduled time outside the Issue queue window."""

    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        super().__init__(detail["message"])


class LineageConflict(Exception):
    """Structured 409 for a lineage mismatch at append/retry time."""

    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        super().__init__(detail["message"])


@dataclass(frozen=True)
class IssueAppendContext:
    """Ordering + lineage facts allocated for a new tail Task inside the lock."""

    issue_sequence: int
    tail_projection: dict[str, Any] | None
    schedule_window: dict[str, Any]


def schedule_window_detail(
    *,
    has_valid_window: bool,
    min_scheduled_at: str | None,
    min_source_task_id: int | None,
    max_scheduled_at: str | None,
    max_source_task_id: int | None,
    message: str = "Scheduled time is outside the current Issue queue window",
) -> dict[str, Any]:
    """Build the common ``issue_schedule_order_conflict`` detail envelope."""
    return {
        "code": SCHEDULE_CONFLICT_CODE,
        "message": message,
        "has_valid_window": has_valid_window,
        "min_scheduled_at": min_scheduled_at,
        "min_source_task_id": min_source_task_id,
        "max_scheduled_at": max_scheduled_at,
        "max_source_task_id": max_source_task_id,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def ensure_issue_order_integrity_locked(
    db: AsyncSession,
    *,
    issue_id: int,
    repair_nulls: bool,
) -> dict[str, Any]:
    """Verify (and optionally repair) task ordering; caller holds the Issue lock.

    Reads the Issue's Tasks in deterministic ``(created_at, id)`` order, checks
    every non-NULL ``issue_sequence`` against that rank, backfills NULL sequences
    and NULL lineage projections when ``repair_nulls`` is set, and raises
    ``IssueOrderIntegrityError`` when the ordering is unrecoverable. Returns a
    report plus the tail projection and current max sequence.
    """
    tasks = (
        (
            await db.execute(
                select(Task)
                .where(Task.issue_id == issue_id)
                .order_by(Task.created_at.asc(), Task.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )

    if not tasks:
        return {
            "repaired_sequences": 0,
            "repaired_projections": 0,
            "blocked": False,
            "max_sequence": 0,
            "tail_projection": None,
        }

    # First pass: any non-NULL sequence that disagrees with the deterministic
    # rank or duplicates another sequence is corruption -> fail closed.
    seen: set[int] = set()
    for rank, task in enumerate(tasks, start=1):
        if task.issue_sequence is not None:
            if task.issue_sequence != rank:
                raise IssueOrderIntegrityError(issue_id, "sequence_mismatch")
            if task.issue_sequence in seen:
                raise IssueOrderIntegrityError(issue_id, "duplicate_sequence")
            seen.add(task.issue_sequence)

    repaired_sequences = 0
    if repair_nulls:
        for rank, task in enumerate(tasks, start=1):
            if task.issue_sequence is None:
                task.issue_sequence = rank
                repaired_sequences += 1
    else:
        for task in tasks:
            if task.issue_sequence is None and task.status in ACTIVE_STATUSES:
                raise IssueOrderIntegrityError(issue_id, "active_null_sequence")

    # Lineage projection repair: backfill NULL projection fields from the frozen
    # Worker snapshot where derivable; an active Task without a verifiable
    # snapshot blocks the whole Issue.
    projection_report = await _repair_lineage_projections(db, issue_id, tasks)
    if projection_report["blocked"]:
        raise IssueOrderIntegrityError(issue_id, projection_report["blocked_reason"])

    max_sequence = max((t.issue_sequence for t in tasks if t.issue_sequence is not None), default=0)
    tail = max(tasks, key=lambda t: (t.issue_sequence or 0))
    tail_projection = _task_projection(tail)
    return {
        "repaired_sequences": repaired_sequences,
        "repaired_projections": projection_report["repaired"],
        "blocked": False,
        "max_sequence": max_sequence,
        "tail_projection": tail_projection,
    }


async def _repair_lineage_projections(
    db: AsyncSession,
    issue_id: int,
    tasks: list[Task],
) -> dict[str, Any]:
    """Backfill NULL projected-lineage fields following the tail lineage.

    Mirrors migration 068 §5.2 for runtime repairs of legacy-NULL rows. An
    active Task whose lineage cannot be derived (missing verifiable snapshot, or
    a ``continue`` crossing the tail namespace) blocks the Issue.
    """
    from app.core.harness_sessions import LEGACY_NAMESPACE, session_namespace_for

    task_ids = [t.id for t in tasks]
    snapshot_rows: dict[int, Any] = {}
    if task_ids:
        from app.models import TaskWorkerProfileSnapshot

        rows = (
            await db.execute(
                select(
                    TaskWorkerProfileSnapshot.task_id,
                    TaskWorkerProfileSnapshot.harness_key,
                    TaskWorkerProfileSnapshot.model_endpoint_snapshot,
                ).where(TaskWorkerProfileSnapshot.task_id.in_(task_ids))
            )
        ).all()
        snapshot_rows = {r.task_id: r for r in rows}

    tail_projection: dict[str, Any] | None = None
    repaired = 0
    for task in sorted(tasks, key=lambda t: (t.created_at, t.id)):
        if _has_full_projection(task):
            tail_projection = _task_projection(task)
            continue

        snapshot = snapshot_rows.get(task.id)
        harness_key = namespace = None
        if snapshot is not None and getattr(snapshot, "harness_key", None):
            harness_key = snapshot.harness_key
            endpoint = getattr(snapshot, "model_endpoint_snapshot", None) or {}
            fingerprint = endpoint.get("fingerprint") if isinstance(endpoint, dict) else None
            namespace = session_namespace_for(harness_key, fingerprint)
        elif task.status in TERMINAL_STATUS_VALUES:
            harness_key = LEGACY_NAMESPACE
            namespace = LEGACY_NAMESPACE

        if harness_key is None:
            if task.status in ACTIVE_STATUSES:
                return {
                    "blocked": True,
                    "blocked_reason": "active_task_missing_snapshot",
                    "repaired": repaired,
                }
            continue  # terminal legacy without snapshot: leave NULL, never blocks

        session_mode = task.session_mode or "continue"
        if tail_projection is None:
            generation = 1 if session_mode == "fresh" else 0
            reset_task_id = task.id if session_mode == "fresh" else None
            reason = "initial"
        elif session_mode == "fresh":
            generation = tail_projection["generation"] + 1
            reset_task_id = task.id
            reason = "fresh"
        elif (
            harness_key == tail_projection["harness_key"]
            and namespace == tail_projection["session_namespace"]
        ):
            generation = tail_projection["generation"]
            reset_task_id = tail_projection["reset_task_id"]
            reason = "inherited"
        else:
            if task.status in ACTIVE_STATUSES:
                return {
                    "blocked": True,
                    "blocked_reason": "continue_namespace_change",
                    "repaired": repaired,
                }
            generation = tail_projection["generation"] + 1
            reset_task_id = task.id
            reason = "legacy_namespace_change"

        task.projected_harness_key = harness_key
        task.projected_session_namespace = namespace
        task.projected_lineage_generation = generation
        task.projected_reset_task_id = reset_task_id
        task.lineage_projection_reason = reason
        repaired += 1
        tail_projection = {
            "harness_key": harness_key,
            "session_namespace": namespace,
            "generation": generation,
            "reset_task_id": reset_task_id,
            "reason": reason,
        }

    return {"blocked": False, "repaired": repaired}


def _has_full_projection(task: Task) -> bool:
    if (
        task.projected_harness_key is None
        or task.projected_session_namespace is None
        or task.projected_lineage_generation is None
        or task.lineage_projection_reason is None
    ):
        return False
    # A reset generation must always point at its establishing Task; only the
    # legacy gen-0 initial projection may carry a NULL reset (design §5.1).
    if task.projected_lineage_generation > 0 and task.projected_reset_task_id is None:
        return False
    return True


def _task_projection(task: Task) -> dict[str, Any] | None:
    if not _has_full_projection(task):
        return None
    return {
        "harness_key": task.projected_harness_key,
        "session_namespace": task.projected_session_namespace,
        "generation": task.projected_lineage_generation,
        "reset_task_id": task.projected_reset_task_id,
        "reason": task.lineage_projection_reason,
    }


async def compute_queue_context(
    db: AsyncSession,
    *,
    issue_id: int,
) -> dict[int, dict[str, Any]]:
    """Batch-compute queue context for every Task in an Issue (no N+1).

    Returns ``{task_id: {...}}`` with ``issue_sequence``, ``queue_position``,
    ``blocked_by_task_id``, ``waiting_reason``, ``lock_owner_task_id`` and
    ``waiting_since``. Terminal tasks get a null queue position.
    """
    tasks = (
        (
            await db.execute(
                select(Task)
                .options(selectinload(Task.worker_profile_snapshot))
                .where(Task.issue_id == issue_id)
                .order_by(Task.issue_sequence.asc().nulls_last(), Task.id.asc())
            )
        )
        .scalars()
        .all()
    )
    lock = (
        await db.execute(
            select(IssueExecutionLock).where(IssueExecutionLock.issue_id == issue_id)
        )
    ).scalar_one_or_none()

    # During the 068 compatibility window any active NULL-sequence Task makes the
    # whole Issue fail closed (spec §3.2.10 / §5.3): no Task gets a healthy
    # queue position, and every active Task projects sequence_repair_required.
    active = [t for t in tasks if t.status in ACTIVE_STATUSES]
    any_active_null = any(t.issue_sequence is None for t in active)
    active_non_null = [t for t in active if t.issue_sequence is not None]
    active_non_null.sort(key=lambda t: t.issue_sequence)
    head = active_non_null[0] if active_non_null else None
    # queue_position is the dynamic position inside the *active* queue only;
    # terminal Tasks never consume a position (spec §7).
    positions = {t.id: i for i, t in enumerate(active_non_null, start=1)}

    # Runtime readiness for the active head's frozen Kit locator, so the head
    # can surface worker_runtime_unavailable with failure detail (§14). Only the
    # head is probed; later tasks keep their predecessor reason.
    head_readiness = None
    head_fingerprint = None
    if head is not None:
        head_snapshot = getattr(head, "worker_profile_snapshot", None)
        head_fingerprint = (
            getattr(head_snapshot, "runtime_locator_fingerprint", None)
            if head_snapshot is not None
            else None
        )
        if head_fingerprint:
            head_readiness = await read_runtime_readiness(db, head_fingerprint)

    # The head's waiting reason when a terminal owner still holds the workspace
    # lock (container not yet drained) is workspace_cleanup.
    lock_owner_task_id = None
    waiting_since = None
    workspace_cleanup = False
    if lock is not None and isinstance(lock, IssueExecutionLock):
        lock_owner_task_id = lock.task_id
        waiting_since = _iso(lock.acquired_at)
        owner = next((t for t in tasks if t.id == lock.task_id), None)
        if owner is not None and owner.status not in ACTIVE_STATUSES:
            workspace_cleanup = True

    def _repair_projection(task: Task) -> dict[str, Any]:
        return {
            "issue_sequence": task.issue_sequence,
            "queue_position": None,
            "blocked_by_task_id": None,
            "waiting_reason": "sequence_repair_required",
            "lock_owner_task_id": None,
            "waiting_since": None,
        }

    result: dict[int, dict[str, Any]] = {}
    for task in tasks:
        if task.status not in ACTIVE_STATUSES:
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": None,
                "blocked_by_task_id": None,
                "waiting_reason": None,
                "lock_owner_task_id": None,
                "waiting_since": None,
            }
            continue

        if task.issue_sequence is None or any_active_null:
            result[task.id] = _repair_projection(task)
            continue

        position = positions.get(task.id)
        if head is not None and task.id != head.id:
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": position,
                "blocked_by_task_id": head.id,
                "waiting_reason": "predecessor",
                "lock_owner_task_id": None,
                "waiting_since": None,
            }
            continue

        # Task is the active head.
        if workspace_cleanup and lock_owner_task_id is not None:
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": position,
                "blocked_by_task_id": None,
                "waiting_reason": "workspace_cleanup",
                "lock_owner_task_id": lock_owner_task_id,
                "waiting_since": waiting_since,
            }
        elif task.scheduled_at is not None and task.scheduled_at > utcnow():
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": position,
                "blocked_by_task_id": None,
                "waiting_reason": "scheduled",
                "lock_owner_task_id": None,
                "waiting_since": None,
            }
        elif head_readiness is not None and head_readiness.is_unavailable:
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": position,
                "blocked_by_task_id": None,
                "waiting_reason": "worker_runtime_unavailable",
                "lock_owner_task_id": None,
                "waiting_since": (
                    head_readiness.checked_at.isoformat()
                    if head_readiness.checked_at
                    else None
                ),
                "runtime_failure_code": head_readiness.failure_code,
                "runtime_failure_message": head_readiness.failure_message,
                "runtime_checked_at": (
                    head_readiness.checked_at.isoformat()
                    if head_readiness.checked_at
                    else None
                ),
                "runtime_locator_fingerprint": head_fingerprint,
            }
        else:
            result[task.id] = {
                "issue_sequence": task.issue_sequence,
                "queue_position": position,
                "blocked_by_task_id": None,
                "waiting_reason": None,
                "lock_owner_task_id": None,
                "waiting_since": None,
            }

    return result


async def compute_schedule_window(
    db: AsyncSession,
    *,
    issue_id: int,
    exclude_task_id: int | None = None,
) -> dict[str, Any]:
    """Return the valid scheduled_at window for an append (no ceiling) or a
    reschedule (floor from earlier active Tasks, ceiling from later ones)."""
    tasks = (
        (
            await db.execute(
                select(Task).where(
                    Task.issue_id == issue_id,
                    Task.status.in_(ACTIVE_STATUS_VALUES),
                )
            )
        )
        .scalars()
        .all()
    )
    # Strong-consistency query: an active NULL sequence during 068 makes the
    # whole Issue fail closed (spec §5.3) instead of silently dropping the NULL
    # predecessor's reservation and risking a monotonic-order violation.
    if any(t.issue_sequence is None for t in tasks):
        raise IssueOrderIntegrityError(issue_id, "active_null_sequence")
    scheduled = [
        t
        for t in tasks
        if t.scheduled_at is not None
        and (exclude_task_id is None or t.id != exclude_task_id)
    ]
    scheduled.sort(
        key=lambda t: (t.issue_sequence if t.issue_sequence is not None else 10**9)
    )

    exclude_seq: int | None = None
    if exclude_task_id is not None:
        for t in tasks:
            if t.id == exclude_task_id:
                exclude_seq = t.issue_sequence
                break

    min_time = None
    min_source = None
    max_time = None
    max_source = None
    for task in scheduled:
        seq = task.issue_sequence
        if exclude_seq is not None:
            # Reschedule: floor from earlier Tasks, ceiling from later ones.
            if seq is not None and seq < exclude_seq:
                if min_time is None or task.scheduled_at > min_time:
                    min_time = task.scheduled_at
                    min_source = task.id
            elif seq is not None and seq > exclude_seq:
                if max_time is None or task.scheduled_at < max_time:
                    max_time = task.scheduled_at
                    max_source = task.id
        else:
            # Append mode: floor is the max scheduled_at of all active Tasks.
            if min_time is None or task.scheduled_at > min_time:
                min_time = task.scheduled_at
                min_source = task.id

    has_valid = min_time is None or max_time is None or min_time <= max_time
    return {
        "has_valid_window": has_valid,
        "min_scheduled_at": _iso(min_time),
        "min_source_task_id": min_source,
        "max_scheduled_at": _iso(max_time),
        "max_source_task_id": max_source,
    }


async def validate_schedule_time_locked(
    db: AsyncSession,
    *,
    issue_id: int,
    scheduled_at: datetime,
    exclude_task_id: int | None = None,
) -> dict[str, Any]:
    """Validate ``scheduled_at`` against the current window; raise structured 409.

    Caller must hold the Issue row lock. Fails closed on an active NULL sequence
    (spec §5.3) before computing any window. On success returns the window used.
    """
    await ensure_issue_order_integrity_locked(
        db,
        issue_id=issue_id,
        repair_nulls=False,
    )
    window = await compute_schedule_window(
        db, issue_id=issue_id, exclude_task_id=exclude_task_id
    )
    if not window["has_valid_window"]:
        raise ScheduleWindowConflict(
            schedule_window_detail(
                has_valid_window=False,
                min_scheduled_at=window["min_scheduled_at"],
                min_source_task_id=window["min_source_task_id"],
                max_scheduled_at=window["max_scheduled_at"],
                max_source_task_id=window["max_source_task_id"],
                message="No valid schedule window exists for this Issue queue",
            )
        )
    if (
        window["min_scheduled_at"] is not None
        and scheduled_at < _parse_dt(window["min_scheduled_at"])
    ):
        raise ScheduleWindowConflict(
            schedule_window_detail(
                has_valid_window=True,
                min_scheduled_at=window["min_scheduled_at"],
                min_source_task_id=window["min_source_task_id"],
                max_scheduled_at=window["max_scheduled_at"],
                max_source_task_id=window["max_source_task_id"],
                message="Scheduled time is before this Issue's queue floor",
            )
        )
    if (
        window["max_scheduled_at"] is not None
        and scheduled_at > _parse_dt(window["max_scheduled_at"])
    ):
        raise ScheduleWindowConflict(
            schedule_window_detail(
                has_valid_window=True,
                min_scheduled_at=window["min_scheduled_at"],
                min_source_task_id=window["min_source_task_id"],
                max_scheduled_at=window["max_scheduled_at"],
                max_source_task_id=window["max_source_task_id"],
                message="Scheduled time is after this Issue's queue ceiling",
            )
        )
    return window


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


async def allocate_next_sequence_locked(
    db: AsyncSession,
    *,
    issue_id: int,
) -> int:
    """Return ``max(issue_sequence) + 1`` for the Issue (caller holds the lock)."""
    max_seq = (
        await db.execute(
            select(func.max(Task.issue_sequence)).where(Task.issue_id == issue_id)
        )
    ).scalar()
    return (max_seq or 0) + 1


async def count_active_successors(
    db: AsyncSession,
    *,
    issue_id: int,
    task_id: int,
) -> int:
    """Count active Tasks whose ``issue_sequence`` is greater than ``task_id``'s.

    Used for the reschedule blast radius: an active head that moves to a future
    time keeps every active successor blocked behind it (§7.3). Returns 0 when
    the Task has no sequence yet (repair-pending compatibility rows).
    """
    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if task is None or task.issue_sequence is None:
        return 0
    count = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.issue_id == issue_id,
                Task.status.in_(ACTIVE_STATUS_VALUES),
                Task.issue_sequence > task.issue_sequence,
            )
        )
    ).scalar()
    return int(count or 0)


def project_tail_lineage(
    tail_projection: dict[str, Any] | None,
    *,
    issue_id: int,
    harness_key: str,
    session_namespace: str,
    session_mode: str,
) -> dict[str, Any]:
    """Allocate generation/reset for a new tail Task from the tail projection.

    ``reset_task_id`` is ``None`` for an ``initial``/``fresh`` generation that
    must be set to the new Task's id after it flushes. A ``continue`` whose
    harness/namespace disagrees with a *verified* tail lineage is a structured
    lineage conflict; a ``legacy`` placeholder tail carries no verifiable
    session evidence (design §5.2 point 5), so the new Task establishes the
    real harness lineage as an initial generation instead of conflicting.
    """
    from app.core.harness_sessions import LEGACY_NAMESPACE

    is_legacy_tail = (
        tail_projection is not None
        and tail_projection["session_namespace"] == LEGACY_NAMESPACE
    )
    if tail_projection is None or is_legacy_tail:
        generation = 1 if session_mode == "fresh" else 0
        reset_task_id: int | None = None
        reason = "initial"
    elif session_mode == "fresh":
        generation = tail_projection["generation"] + 1
        reset_task_id = None
        reason = "fresh"
    elif (
        harness_key == tail_projection["harness_key"]
        and session_namespace == tail_projection["session_namespace"]
    ):
        generation = tail_projection["generation"]
        reset_task_id = tail_projection["reset_task_id"]
        reason = "inherited"
    else:
        raise LineageConflict(
            {
                "code": LINEAGE_CONFLICT_CODE,
                "message": "Continue task does not match the Issue tail session lineage",
                "issue_id": issue_id,
                "tail_lineage": {
                    "harness_key": tail_projection["harness_key"],
                    "session_namespace": tail_projection["session_namespace"],
                    "generation": tail_projection["generation"],
                    "reset_task_id": tail_projection["reset_task_id"],
                },
            }
        )

    return {
        "harness_key": harness_key,
        "session_namespace": session_namespace,
        "generation": generation,
        "reset_task_id": reset_task_id,
        "reason": reason,
    }
