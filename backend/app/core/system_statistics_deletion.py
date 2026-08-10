"""Unified lifecycle-statistics archival before Task/Issue deletion.

Implements the system lifecycle statistics design §7: a single service that
snapshots an Issue and every Task about to be deleted inside the caller's
existing database transaction. The business delete then proceeds in the same
transaction — if the archive fails, the whole delete rolls back.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.utcnow import utcnow
from app.models import (
    AIProvider,
    DeletedIssueStatistics,
    DeletedTaskStatistics,
    Issue,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
)

_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

# Mirrors app.core.system_data_cleanup.ACTIVE_TASK_STATUS_VALUES so the archived
# forced_with_active_tasks flag and the cleanup skip decision agree (§6.2).
_ACTIVE_TASK_STATUS_VALUES = {
    TaskStatus.PENDING.value,
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
}

_TASK_ARCHIVE_SET_COLUMNS = [
    "source_issue_id",
    "project_id",
    "initiator_user_id",
    "provider_id",
    "provider_name_snapshot",
    "provider_model_snapshot",
    "harness_key",
    "adapter_version",
    "cli_version",
    "worker_profile_id",
    "worker_profile_name_snapshot",
    "task_mode",
    "trigger_source",
    "priority",
    "is_retry",
    "last_status",
    "deleted_before_terminal",
    "is_manually_overridden",
    "created_at",
    "scheduled_at",
    "started_at",
    "terminal_at",
    "input_tokens",
    "output_tokens",
    "additions",
    "deletions",
    "total_changes",
    "change_data_available",
    "source_deleted_at",
    "deletion_reason",
    "deleted_by_user_id",
    "schema_version",
    "archived_at",
]

_ISSUE_ARCHIVE_SET_COLUMNS = [
    "project_id",
    "initiator_user_id",
    "created_at",
    "last_status",
    "had_merge_request",
    "source_deleted_at",
    "deletion_reason",
    "deleted_by_user_id",
    "forced_with_active_tasks",
    "schema_version",
    "archived_at",
]


def _provider_snapshot(task: Task) -> dict:
    return task.provider_runtime_snapshot or {}


def _task_archive_row(
    task: Task,
    snapshot: TaskWorkerProfileSnapshot | None,
    provider: AIProvider | None,
    worker_profile: WorkerProfile | None,
    *,
    deleted_at: datetime,
    deletion_reason: str,
    deleted_by_user_id: int | None,
) -> dict:
    """Build the normalized archive row for one Task (design §6.5 priority).

    The value priority here must stay identical to the SQL normalization used
    by the current-task branch of the lifecycle query so a Task does not move
    to a different grouping when it is archived.
    """
    runtime = _provider_snapshot(task)

    provider_id = runtime.get("provider_id")
    if provider_id is None:
        provider_id = task.provider_id

    provider_name = runtime.get("provider_name") or (provider.name if provider else None)
    provider_model = (
        task.model_name
        or runtime.get("configured_model")
        or (provider.model if provider else None)
    )

    harness_key = None
    adapter_version = None
    cli_version = None
    worker_profile_id = None
    worker_profile_name = None
    if snapshot is not None:
        harness_key = snapshot.harness_key or task.projected_harness_key
        adapter_version = snapshot.harness_adapter_version
        cli_version = snapshot.cli_version
        worker_profile_id = snapshot.worker_profile_id
        worker_profile_name = snapshot.profile_name or (
            worker_profile.name if worker_profile else None
        )
    else:
        harness_key = task.projected_harness_key
        worker_profile_id = task.worker_profile_id
        worker_profile_name = worker_profile.name if worker_profile else None

    is_terminal = task.status in _TERMINAL_STATUSES
    change_data_available = task.change_stats_recorded_at is not None

    return {
        "source_task_id": task.id,
        "source_issue_id": task.issue_id,
        "project_id": task.project_id,
        "initiator_user_id": task.initiator_user_id,
        "provider_id": provider_id,
        "provider_name_snapshot": provider_name,
        "provider_model_snapshot": provider_model,
        "harness_key": harness_key,
        "adapter_version": adapter_version,
        "cli_version": cli_version,
        "worker_profile_id": worker_profile_id,
        "worker_profile_name_snapshot": worker_profile_name,
        "task_mode": task.task_mode,
        "trigger_source": task.trigger_source,
        "priority": task.priority,
        "is_retry": task.is_retry,
        "last_status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
        "deleted_before_terminal": not is_terminal,
        "is_manually_overridden": task.is_manually_overridden,
        "created_at": task.created_at,
        "scheduled_at": task.scheduled_at,
        "started_at": task.started_at,
        "terminal_at": task.completed_at if is_terminal else None,
        "input_tokens": task.input_tokens,
        "output_tokens": task.output_tokens,
        "additions": task.additions if change_data_available else None,
        "deletions": task.deletions if change_data_available else None,
        "total_changes": task.total_changes if change_data_available else None,
        "change_data_available": change_data_available,
        "source_deleted_at": deleted_at,
        "deletion_reason": deletion_reason,
        "deleted_by_user_id": deleted_by_user_id,
        "schema_version": 1,
        "archived_at": deleted_at,
    }


def _issue_archive_row(
    issue: Issue,
    *,
    deleted_at: datetime,
    deletion_reason: str,
    deleted_by_user_id: int | None,
    forced_with_active_tasks: bool,
) -> dict:
    had_merge_request = issue.merge_request_iid is not None or bool(issue.merge_request_url)
    return {
        "source_issue_id": issue.id,
        "project_id": issue.project_id,
        "initiator_user_id": issue.initiator_user_id,
        "created_at": issue.created_at,
        "last_status": issue.status,
        "had_merge_request": had_merge_request,
        "source_deleted_at": deleted_at,
        "deletion_reason": deletion_reason,
        "deleted_by_user_id": deleted_by_user_id,
        "forced_with_active_tasks": forced_with_active_tasks,
        "schema_version": 1,
        "archived_at": deleted_at,
    }


def _dialect_insert(model: type, dialect: str):
    if dialect == "postgresql":
        return pg_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError(
        f"lifecycle archive unsupported on dialect {dialect!r} "
        "(expected postgresql or sqlite)"
    )


def _task_upsert_statement(dialect: str):
    base = _dialect_insert(DeletedTaskStatistics, dialect)
    return base.on_conflict_do_update(
        index_elements=[DeletedTaskStatistics.source_task_id],
        set_={col: getattr(base.excluded, col) for col in _TASK_ARCHIVE_SET_COLUMNS},
    )


def _issue_upsert_statement(dialect: str):
    base = _dialect_insert(DeletedIssueStatistics, dialect)
    return base.on_conflict_do_update(
        index_elements=[DeletedIssueStatistics.source_issue_id],
        set_={col: getattr(base.excluded, col) for col in _ISSUE_ARCHIVE_SET_COLUMNS},
    )


def _task_is_active(task: Task) -> bool:
    """True when a Task is still active (pending/queued/running or containerized).

    Evaluated over the lock-time ``FOR UPDATE`` read so the archived
    ``forced_with_active_tasks`` flag reflects reality at lock time (§6.2).
    """
    if bool(task.container_id):
        return True
    if isinstance(task.status, TaskStatus):
        return task.status.value in _ACTIVE_TASK_STATUS_VALUES
    return str(task.status) in _ACTIVE_TASK_STATUS_VALUES


async def archive_issue_statistics_before_delete(
    db: AsyncSession,
    *,
    issue_id: int,
    deletion_reason: str = "manual",
    deleted_by_user_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Snapshot an Issue and all its Tasks right before business-row deletion.

    Must run inside the caller's deletion transaction, with the Issue row
    already (or newly) locked. Computes ``forced_with_active_tasks`` from the
    lock-time Task state (§6.2) and writes it on the Issue archive row. Returns
    the number of Tasks archived. Raises if the archive rows cannot be written
    or validated, which rolls the enclosing business delete back.
    """
    deleted_at = now or utcnow()

    issue = (
        await db.execute(select(Issue).where(Issue.id == issue_id).with_for_update())
    ).scalar_one_or_none()
    if issue is None:
        raise ValueError(f"Issue {issue_id} not found for lifecycle archive")

    tasks = list(
        (
            await db.execute(
                select(Task)
                .where(Task.issue_id == issue.id)
                .order_by(Task.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
                .options(undefer(Task.provider_runtime_snapshot))
            )
        )
        .scalars()
        .all()
    )

    # Lock-time reality: the Task rows above are the FOR UPDATE, populate_existing
    # read, so any state change made by a concurrent worker before we locked is
    # already visible here (§6.2).
    forced_with_active_tasks = any(_task_is_active(task) for task in tasks)

    snapshot_by_task: dict[int, TaskWorkerProfileSnapshot] = {}
    provider_by_id: dict[int, AIProvider] = {}
    worker_profile_by_id: dict[int, WorkerProfile] = {}

    if tasks:
        snap_rows = (
            await db.execute(
                select(TaskWorkerProfileSnapshot).where(
                    TaskWorkerProfileSnapshot.task_id.in_([task.id for task in tasks])
                )
            )
        ).scalars().all()
        snapshot_by_task = {snap.task_id: snap for snap in snap_rows}

        provider_ids = {task.provider_id for task in tasks if task.provider_id is not None}
        if provider_ids:
            provider_rows = (
                await db.execute(select(AIProvider).where(AIProvider.id.in_(provider_ids)))
            ).scalars().all()
            provider_by_id = {provider.id: provider for provider in provider_rows}

        worker_profile_ids = {
            task.worker_profile_id for task in tasks if task.worker_profile_id is not None
        }
        if worker_profile_ids:
            profile_rows = (
                await db.execute(
                    select(WorkerProfile).where(WorkerProfile.id.in_(worker_profile_ids))
                )
            ).scalars().all()
            worker_profile_by_id = {profile.id: profile for profile in profile_rows}

    task_rows = [
        _task_archive_row(
            task,
            snapshot_by_task.get(task.id),
            provider_by_id.get(task.provider_id),
            worker_profile_by_id.get(task.worker_profile_id),
            deleted_at=deleted_at,
            deletion_reason=deletion_reason,
            deleted_by_user_id=deleted_by_user_id,
        )
        for task in tasks
    ]

    dialect = db.bind.dialect.name
    task_stmt = _task_upsert_statement(dialect)
    issue_stmt = _issue_upsert_statement(dialect)

    if task_rows:
        await db.execute(task_stmt, task_rows)
    await db.execute(
        issue_stmt,
        [
            _issue_archive_row(
                issue,
                deleted_at=deleted_at,
                deletion_reason=deletion_reason,
                deleted_by_user_id=deleted_by_user_id,
                forced_with_active_tasks=forced_with_active_tasks,
            )
        ],
    )
    await db.flush()

    archived_count = (
        await db.execute(
            select(DeletedTaskStatistics.id).where(
                DeletedTaskStatistics.source_issue_id == issue.id
            )
        )
    ).scalars().all()
    if len(archived_count) != len(tasks):
        raise RuntimeError(
            f"lifecycle archive row count mismatch for issue {issue.id}: "
            f"expected {len(tasks)}, archived {len(archived_count)}"
        )

    return len(tasks)
