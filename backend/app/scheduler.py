"""Task scheduler for queue management."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from docker.errors import NotFound
from sqlalchemy import case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.config import get_effective_settings as get_settings
from app.core.docker_client import (
    DockerClientWrapper,
    DockerConnectionConfig,
    get_docker_client,
)
from app.core.harness_execution_policy import legacy_rejection_detail
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.issue_execution_locks import (
    acquire_issue_execution_lock,
    cleanup_inactive_issue_execution_locks,
    release_issue_execution_lock,
)
from app.core.issue_task_order import (
    ACTIVE_STATUS_VALUES,
    ACTIVE_STATUSES,
    IssueOrderIntegrityError,
    ensure_issue_order_integrity_locked,
)
from app.core.session import cleanup_stale_sessions
from app.core.task_helpers import maybe_update_issue_status
from app.core.task_log_payloads import persist_raw_log_snapshot
from app.core.usage_limits import (
    UsageLimitExceeded,
    get_usage_quota_service,
    usage_limit_exceeded_detail,
)
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import (
    DockerConnectionsUnavailableError,
    TaskContainerLookupError,
    TaskContainerNotFoundError,
    connection_for_task,
    connection_from_snapshot,
    docker_daemon_key,
    find_task_container,
    list_known_docker_targets,
)
from app.core.worker_runtime_readiness import (
    READINESS_UNAVAILABLE,
    RuntimeProbeTransientError,
    RuntimeReadiness,
    read_runtime_readiness,
    run_deterministic_kit_probe,
)
from app.core.worker_workspace import cleanup_expired_ci_failure_bundles
from app.core.worker_workspace_remote import remove_issue_workspace_remote
from app.database import AsyncSessionLocal
from app.models import (
    Issue,
    IssueExecutionLock,
    IssueStatus,
    Task,
    TaskRunArchive,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerRuntimeReadiness,
)
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
_SESSION_CLEANUP_INTERVAL_SECONDS = 3600
_RUNTIME_ARCHIVE_CLEANUP_INTERVAL_SECONDS = 3600
_RUNTIME_ARCHIVE_CLEANUP_RETRY_SECONDS = 3600
_RUNTIME_ARCHIVE_CLEANUP_BATCH_SIZE = 100
_WORKSPACE_CLEANUP_INTERVAL_SECONDS = 21600
_WORKSPACE_CLEANUP_BATCH_SIZE = 50
_RETAINED_CONTAINER_CLEANUP_INTERVAL_SECONDS = 60
_RETAINED_CONTAINER_CLEANUP_BATCH_SIZE = 20
_LOCK_CLEANUP_INTERVAL_SECONDS = 300
_TERMINAL_WORKER_STUCK_SECONDS = 120
_RECOVERY_RETRY_OFFSETS_SECONDS = (0.0, 10.0, 20.0)
_RECOVERY_REQUEST_TIMEOUT_SECONDS = 5
_RECOVERY_PROBE_TIMEOUT_SECONDS = 11
_RECOVERY_UNAVAILABLE_RETRY_SECONDS = 30
_QUIESCENT_CONTAINER_STATUSES = {"created", "exited", "dead", "removing"}

# Thread pool for running worker tasks (to avoid blocking the event loop)
_worker_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="worker-")


def _get_container_pattern() -> re.Pattern:
    """Build container name regex using configured prefix."""
    prefix = re.escape(get_settings().worker_container_prefix)
    return re.compile(rf"^{prefix}-(\d+)-issue(\d+)$")


def _extract_task_id(container_name: str) -> int | None:
    """Extract task_id from a worker container name like codify-123-issue456."""
    m = _get_container_pattern().match(container_name)
    return int(m.group(1)) if m else None


def _get_recovery_docker_client(connection):
    """Create a bounded, non-cached client for startup recovery."""
    return DockerClientWrapper(
        connection,
        connect_timeout=_RECOVERY_REQUEST_TIMEOUT_SECONDS,
        operation_timeout=_RECOVERY_REQUEST_TIMEOUT_SECONDS,
    )


def _list_recovery_containers(connection, container_prefix: str):
    """Probe one daemon and close the transient client afterwards."""
    docker = _get_recovery_docker_client(connection)
    try:
        return docker.client.containers.list(
            all=True,
            filters={"name": f"{container_prefix}-"},
        )
    finally:
        docker.close()


def _inspect_recovery_container(connection, container_reference: str) -> tuple[str, str]:
    """Resolve one known container through a bounded transient recovery client."""
    docker = _get_recovery_docker_client(connection)
    try:
        container = docker.client.containers.get(container_reference)
        return container.name, container.status
    finally:
        docker.close()


async def _stop_recovered_cancelled_container(container, task_id: int) -> None:
    """Stop a recovered container before releasing its Issue execution slot."""
    try:
        await asyncio.to_thread(container.stop, timeout=10)
    except NotFound:
        return
    except Exception as stop_error:  # noqa: BLE001
        logger.warning(
            "Graceful stop failed for recovered cancelled task %s: %s; forcing stop",
            task_id,
            stop_error,
        )
        try:
            await asyncio.to_thread(container.kill)
        except NotFound:
            return
        except Exception as kill_error:  # noqa: BLE001
            raise RuntimeError(
                f"could not stop recovered cancelled container: graceful={stop_error}; "
                f"force={kill_error}"
            ) from kill_error


async def _finalize_recovered_raw_logs(
    db: AsyncSession,
    docker: DockerClientWrapper,
    task: Task,
    container,
) -> None:
    """Persist stable raw logs before a recovered non-runnable container is removed."""
    if task.raw_logs_finalized_at is not None:
        return
    try:
        raw_console_log = await asyncio.to_thread(
            docker.read_file_from_container,
            container,
            "/tmp/codify-runtime/console.log",
        )
    except Exception:  # noqa: BLE001
        raw_console_log = None
    if not isinstance(raw_console_log, bytes):
        raw_console_log = await asyncio.to_thread(
            docker.get_container_logs,
            container,
        )
    if not isinstance(raw_console_log, bytes):
        raise RuntimeError(f"Could not finalize recovered task {task.id} raw logs")
    await persist_raw_log_snapshot(
        db,
        task_id=task.id,
        content=raw_console_log,
    )
    task.raw_logs_finalized_at = utcnow()
    await db.commit()


class Scheduler:
    """Task scheduler with priority queue and concurrency control."""

    def __init__(self) -> None:
        self.running = False
        # Stable per-process boot id for structured events; the in-memory
        # "log only on state change" dedupe cache resets with each restart.
        self.scheduler_boot_id = uuid.uuid4().hex
        self._running_tasks: set[int] = set()  # task_ids currently running
        self._running_issues: set[int] = set()  # issue_ids with running tasks
        self._retained_container_blocked_issues: set[int] = set()
        self._worker_tasks: dict[int, asyncio.Task] = {}  # scheduler task handles by task_id
        self._terminal_worker_seen_at: dict[int, float] = {}
        self._active_worker_threads: int = 0  # thread pool tasks in-flight (submitted but not done)
        self._last_session_cleanup_at = 0.0
        self._last_runtime_archive_cleanup_at = time.time()
        self._last_workspace_cleanup_at = 0.0
        self._last_retained_container_cleanup_at = 0.0
        self._last_lock_cleanup_at = 0.0
        self._workspace_cleanup_task: asyncio.Task | None = None
        self._retained_container_cleanup_task: asyncio.Task | None = None

    def _emit_event(self, event: str, *, reason: str, issue_id=None, task_id=None, **extra) -> None:
        """Emit one single-line structured JSON event (spec §9).

        Event names are stable and free of secrets; consumers use
        ``scheduler_boot_id + event + issue_id + task_id + observed state`` to
        dedupe across restarts.
        """
        payload: dict = {
            "event": event,
            "occurred_at": utcnow().isoformat(),
            "scheduler_boot_id": self.scheduler_boot_id,
            "reason": reason,
        }
        if issue_id is not None:
            payload["issue_id"] = issue_id
        if task_id is not None:
            payload["task_id"] = task_id
        payload.update({k: v for k, v in extra.items() if v is not None})
        logger.warning(json.dumps(payload, default=str))

    async def _release_issue_lock(
        self,
        db: AsyncSession,
        *,
        issue_id: int,
        owner_task_id: int,
    ) -> None:
        """Release an issue execution lock only when this task still owns it."""
        released = await release_issue_execution_lock(
            db,
            issue_id=issue_id,
            owner_task_id=owner_task_id,
        )
        if not released:
            self._emit_event(
                "issue_lock_release_owner_mismatch",
                reason="lock_not_owned_or_already_released",
                issue_id=issue_id,
                task_id=owner_task_id,
            )

    async def _remediate_legacy_contracts(self, db: AsyncSession) -> set[int]:
        """Under ``HARNESS_EXECUTION_MODE=v2_only``, terminalize legacy V1 contracts.

        Idempotent remediation (phase1-design §2.3): a task whose frozen bundle
        contract is not canonical V2 is not executable. RUNNING tasks are failed
        closed (legacy container is not resumed; the retained-container cleanup
        stops the physical container by name) and PENDING/QUEUED tasks are
        cancelled without ever dispatching. Each task is processed at most once
        because it becomes terminal. Returns the set of terminalized task ids.
        """
        row = await db.execute(
            select(Task)
            .where(
                Task.status.in_(
                    (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
                )
            )
            .options(selectinload(Task.runtime_bundle))
        )
        terminalized: set[int] = set()
        terminalized_issues: set[int] = set()
        for task in row.scalars().all():
            bundle = task.runtime_bundle
            contract_version = getattr(bundle, "contract_version", None)
            if contract_version == HARNESS_CONTRACT_VERSION_V2:
                continue
            is_running = getattr(task.status, "value", task.status) == TaskStatus.RUNNING.value
            cancelled = is_running and isinstance(
                getattr(task, "cancel_requested_at", None), datetime
            )
            task.status = TaskStatus.CANCELLED if (cancelled or not is_running) else TaskStatus.FAILED
            task.error_message = legacy_rejection_detail(task.id)["message"]
            task.completed_at = utcnow()
            if not is_running:
                # A never-dispatched legacy task has no live container to reap.
                task.container_id = None
            # A RUNNING legacy task keeps its container_id so the retained-container
            # cleanup (matched on container_id IS NOT NULL) finds and physically
            # stops the still-alive container instead of leaving an orphan behind.
            if task.issue_id is not None:
                await self._release_issue_lock(
                    db,
                    issue_id=task.issue_id,
                    owner_task_id=task.id,
                )
                terminalized_issues.add(task.issue_id)
            await db.flush()
            terminalized.add(task.id)
            logger.warning(
                "v2_only remediation: terminalized legacy task %s as %s "
                "(contract_version=%r)",
                task.id,
                task.status.value,
                contract_version,
            )
        if terminalized:
            await db.commit()
            for issue_id in terminalized_issues:
                self._running_issues.discard(issue_id)
        return terminalized

    async def _startup_sequence_audit(self, db: AsyncSession) -> None:
        """Re-emit abnormal/waiting ordering states once per boot (spec §9).

        The audit runs before task dispatch and is the only place that re-logs
        pre-existing states; the periodic cycle logs only on change.
        """
        rows = (
            await db.execute(
                select(
                    Task.id,
                    Task.issue_id,
                    Task.issue_sequence,
                    Task.status,
                ).where(
                    Task.status.in_(ACTIVE_STATUS_VALUES),
                    or_(
                        Task.issue_sequence.is_(None),
                        Task.status == TaskStatus.QUEUED,
                    ),
                )
            )
        ).all()
        for row in rows:
            task_id, issue_id, issue_sequence, status = row
            if issue_sequence is None:
                self._emit_event(
                    "issue_sequence_integrity_failed",
                    reason="active_null_sequence",
                    issue_id=issue_id,
                    task_id=task_id,
                    issue_sequence=None,
                    recovered=True,
                )
            elif status == TaskStatus.QUEUED:
                self._emit_event(
                    "issue_queue_head_promoted",
                    reason="recovered",
                    issue_id=issue_id,
                    task_id=task_id,
                    issue_sequence=issue_sequence,
                    recovered=True,
                )
        await db.commit()

    async def start(self) -> None:
        """Start the scheduler loop."""
        logger.info("Starting scheduler...")
        self.running = True

        # Never dispatch new work after an inconclusive startup audit. Per-daemon
        # outages are handled inside _crash_recovery with deferred ownership; an
        # unexpected top-level failure means we cannot safely prove that old
        # containers are not still mutating daemon-local Issue workspaces.
        while self.running:
            try:
                await self._crash_recovery()
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Crash recovery failed; retrying before task dispatch: %s",
                    exc,
                )
                await asyncio.sleep(get_settings().scheduler_interval)

        if not self.running:
            logger.info("Scheduler stopped before startup recovery completed")
            return

        try:
            async with AsyncSessionLocal() as db:
                await self._startup_sequence_audit(db)
        except Exception:  # noqa: BLE001
            logger.exception("Startup sequence audit failed; cycle will repair in-band")

        while self.running:
            try:
                await self._run_cycle()
            except Exception:
                logger.exception("Scheduler cycle failed")
            settings = get_settings()
            await asyncio.sleep(settings.scheduler_interval)

        logger.info("Scheduler stopped")

    async def stop(self) -> None:
        """Stop the scheduler."""
        logger.info("Stopping scheduler...")
        self.running = False
        cleanup_task = self._workspace_cleanup_task
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task
        retained_cleanup_task = self._retained_container_cleanup_task
        if retained_cleanup_task is not None and not retained_cleanup_task.done():
            retained_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retained_cleanup_task

    async def _run_cycle(self) -> None:
        """Run one scheduler cycle."""
        async with AsyncSessionLocal() as db:
            await load_runtime_config_from_db(db)
            await self._maybe_cleanup_sessions(db)
            await self._maybe_cleanup_runtime_archives(db)
            await self._maybe_cleanup_workspaces(db)
            await self._maybe_cleanup_retained_containers(db)
            await self._maybe_cleanup_issue_locks(db)

            # Reconcile in-memory tracking sets against DB and local worker handles.
            # A task can be terminal in DB while its worker coroutine is still doing
            # post-run cleanup, so status alone is not enough to declare it stale.
            await self._reconcile_running_state(db)

            # Transition eligible PENDING tasks → QUEUED
            await self._mark_eligible_as_queued(db)

            settings = get_settings()
            # Count running tasks for concurrency control
            running_count = await self._get_running_count(db)

            if running_count >= settings.max_concurrency:
                logger.debug(
                    f"Max concurrency reached ({running_count}/{settings.max_concurrency})"
                )
                return

            # Get next task
            task = await self._get_next_task(db)
            if not task:
                logger.debug("No tasks available")
                return

            # Check issue mutex — prevents concurrent tasks on the same issue.
            # Tasks without issue_id are independent and skip the shared mutex.
            if task.issue_id in self._running_issues:
                logger.debug(f"Issue {task.issue_id} already running, skipping")
                return

            # Execute task
            await self._execute_task(db, task)

    async def _reconcile_running_state(self, db: AsyncSession) -> None:
        """Reconcile in-memory running-task sets against the database.

        When a worker thread blocks indefinitely (e.g., on a GitLab API call with no
        timeout), its finally block never executes, so _running_tasks and _running_issues
        are never cleared even after the DB task has moved out of RUNNING. This method
        keeps normal post-run cleanup active by checking the local asyncio task handle,
        and corrects real drift every cycle.
        """
        await self._reconcile_retained_issue_blocks(db)
        if not self._running_tasks and not self._running_issues:
            return

        if self._running_tasks:
            result = await db.execute(
                select(Task.id, Task.issue_id, Task.status).where(
                    Task.id.in_(list(self._running_tasks)),
                )
            )
            rows = result.fetchall()
            active_task_ids: set[int] = set()
            active_issue_ids: set[int] = set()
            for row in rows:
                task_id = row[0]
                issue_id = row[1]
                status = row[2] if len(row) > 2 else TaskStatus.RUNNING
                status_value = getattr(status, "value", status)
                if status_value == TaskStatus.RUNNING.value:
                    self._terminal_worker_seen_at.pop(task_id, None)
                    active_task_ids.add(task_id)
                    if issue_id is not None:
                        active_issue_ids.add(issue_id)
                    continue

                if self._worker_handle_is_active(task_id, status):
                    active_task_ids.add(task_id)
                    if issue_id is not None:
                        active_issue_ids.add(issue_id)

            stale_tasks = self._running_tasks - active_task_ids
            for task_id in stale_tasks:
                self._running_tasks.discard(task_id)
                self._forget_worker_handle_if_finished(task_id)
                logger.warning(
                    "Reconciled stale _running_tasks entry for task %s "
                    "(no longer RUNNING in DB and worker handle is inactive or stuck)",
                    task_id,
                )

            active_issue_ids.update(self._retained_container_blocked_issues)
            stale_issues = self._running_issues - active_issue_ids
            for issue_id in stale_issues:
                self._running_issues.discard(issue_id)
                logger.warning(
                    "Reconciled stale _running_issues entry for issue %s "
                    "(no RUNNING task or active worker handle within stuck threshold found)",
                    issue_id,
                )

        elif self._running_issues:
            # _running_tasks is empty but _running_issues has entries — possible when a
            # thread's finally block could not release the issue slot.  Query independently.
            result = await db.execute(
                select(Task.issue_id)
                .distinct()
                .where(
                    Task.issue_id.in_(list(self._running_issues)),
                    Task.status == TaskStatus.RUNNING,
                )
            )
            active_issue_ids = {row[0] for row in result.fetchall() if row[0] is not None}
            active_issue_ids.update(self._retained_container_blocked_issues)
            for issue_id in self._running_issues - active_issue_ids:
                self._running_issues.discard(issue_id)
                logger.warning(
                    "Reconciled stale _running_issues entry for issue %s "
                    "(no RUNNING task found in DB)",
                    issue_id,
                )

    async def _reconcile_retained_issue_blocks(self, db: AsyncSession) -> None:
        """Discover retained containers and release blocks after they are gone."""
        result = await db.execute(
            select(Task.issue_id)
            .distinct()
            .where(
                Task.status.in_(
                    (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                ),
                Task.container_id.is_not(None),
            )
        )
        still_retained = {row[0] for row in result.fetchall() if row[0] is not None}
        discovered = still_retained - self._retained_container_blocked_issues
        if discovered:
            self._retained_container_blocked_issues.update(discovered)
            logger.warning(
                "Blocked %s Issue(s) whose terminal tasks retain worker containers",
                len(discovered),
            )
        self._running_issues.update(still_retained)
        released = self._retained_container_blocked_issues - still_retained
        if released:
            self._retained_container_blocked_issues.difference_update(released)
            logger.info(
                "Released %s Issue container-recovery block(s)",
                len(released),
            )

    def _block_issue_for_retained_container(self, task: Task) -> bool:
        """Keep one Issue unavailable while a durable container reference exists."""
        container_reference = getattr(task, "container_id", None)
        issue_id = getattr(task, "issue_id", None)
        if (
            not isinstance(container_reference, str)
            or not container_reference.strip()
            or not isinstance(issue_id, int)
        ):
            return False
        self._retained_container_blocked_issues.add(issue_id)
        self._running_issues.add(issue_id)
        return True

    async def _clear_retained_container_reference(
        self,
        db: AsyncSession,
        task: Task,
    ) -> None:
        """Clear one container reference and release its lock if it is the last one.

        The lock release is owner-qualified: only this Task's ``(issue_id, task_id)``
        pair may be deleted, so a lock re-acquired by a newer Task is never removed
        (spec §6.6/§6.7).
        """
        task.container_id = None
        other_container_exists = (
            select(Task.id)
            .where(
                Task.issue_id == task.issue_id,
                Task.id != task.id,
                Task.container_id.is_not(None),
            )
            .exists()
        )
        release_result = await db.execute(
            delete(IssueExecutionLock).where(
                IssueExecutionLock.issue_id == task.issue_id,
                IssueExecutionLock.task_id == task.id,
                ~other_container_exists,
            )
        )
        await db.commit()
        if release_result.rowcount:
            self._retained_container_blocked_issues.discard(task.issue_id)
            self._running_issues.discard(task.issue_id)
            logger.info(
                "Released Issue %s after task %s retained container was reconciled",
                task.issue_id,
                task.id,
            )

    def _worker_handle_is_active(self, task_id: int, status) -> bool:
        """Return True while the local worker coroutine is still doing cleanup."""
        status_value = getattr(status, "value", status)
        if status_value == TaskStatus.CANCELLED.value:
            return False

        worker_task = self._worker_tasks.get(task_id)
        if worker_task is None or worker_task.done():
            return False

        now = time.monotonic()
        first_seen = self._terminal_worker_seen_at.setdefault(task_id, now)
        elapsed = now - first_seen
        if elapsed < _TERMINAL_WORKER_STUCK_SECONDS:
            logger.debug(
                "Task %s is %s in DB but worker coroutine is still active "
                "(post-run cleanup, %.0fs)",
                task_id,
                status,
                elapsed,
            )
            return True

        logger.warning(
            "Task %s worker coroutine still active %.0fs after DB status became %s; "
            "reconciling as stale",
            task_id,
            elapsed,
            status,
        )
        return False

    def _forget_worker_handle_if_finished(self, task_id: int) -> None:
        """Drop completed handles, but keep active stuck handles observable."""
        worker_task = self._worker_tasks.get(task_id)
        if worker_task is not None and not worker_task.done():
            return
        self._worker_tasks.pop(task_id, None)
        self._terminal_worker_seen_at.pop(task_id, None)

    async def _maybe_cleanup_sessions(self, db: AsyncSession) -> None:
        """Periodically delete long-stale dashboard sessions."""
        now = time.time()
        if now - self._last_session_cleanup_at < _SESSION_CLEANUP_INTERVAL_SECONDS:
            return

        deleted_count = await cleanup_stale_sessions(db)
        if deleted_count:
            await db.commit()
            logger.info("Cleaned up %s stale dashboard sessions", deleted_count)
        self._last_session_cleanup_at = now

    async def _maybe_cleanup_runtime_archives(self, db: AsyncSession) -> None:
        """Delete expired runtime archive files without deleting their Tasks."""
        now = time.time()
        if (
            now - self._last_runtime_archive_cleanup_at
            < _RUNTIME_ARCHIVE_CLEANUP_INTERVAL_SECONDS
        ):
            return

        retention_days = get_settings().worker_runtime_archive_retention_days
        current_time = utcnow()
        cutoff = current_time - timedelta(days=retention_days)
        archives = list(
            (
                await db.execute(
                    select(TaskRunArchive)
                    .where(
                        TaskRunArchive.created_at < cutoff,
                        or_(
                            TaskRunArchive.cleanup_next_attempt_at.is_(None),
                            TaskRunArchive.cleanup_next_attempt_at <= current_time,
                        ),
                    )
                    .order_by(TaskRunArchive.created_at.asc(), TaskRunArchive.id.asc())
                    .limit(_RUNTIME_ARCHIVE_CLEANUP_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
        deleted = 0
        failed = 0
        retry_at = current_time + timedelta(seconds=_RUNTIME_ARCHIVE_CLEANUP_RETRY_SECONDS)
        for archive in archives:
            try:
                await asyncio.to_thread(os.remove, archive.archive_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning(
                    "Could not delete expired runtime archive %s: %s",
                    archive.archive_path,
                    exc,
                )
                archive.cleanup_next_attempt_at = retry_at
                failed += 1
                continue
            await db.delete(archive)
            deleted += 1

        if deleted or failed:
            await db.commit()
        if deleted:
            logger.info("Deleted %s expired runtime archive(s)", deleted)
        if len(archives) < _RUNTIME_ARCHIVE_CLEANUP_BATCH_SIZE:
            self._last_runtime_archive_cleanup_at = now

    async def _maybe_cleanup_workspaces(self, db: AsyncSession) -> None:
        """Start periodic workspace cleanup without blocking the scheduler cycle."""
        del db
        now = time.time()
        if now - self._last_workspace_cleanup_at < _WORKSPACE_CLEANUP_INTERVAL_SECONDS:
            return
        if self._workspace_cleanup_task is not None and not self._workspace_cleanup_task.done():
            return

        settings = get_settings()
        raw_root = getattr(settings, "worker_workspace_host_path", "")
        root = raw_root.strip() if isinstance(raw_root, str) else ""
        if not root:
            self._last_workspace_cleanup_at = now
            return
        retention_days = getattr(settings, "worker_workspace_retention_days", 14)
        if not isinstance(retention_days, int):
            self._last_workspace_cleanup_at = now
            return
        if retention_days <= 0:
            self._last_workspace_cleanup_at = now
            return

        self._last_workspace_cleanup_at = now
        cleanup_task = asyncio.create_task(
            self._run_workspace_cleanup(settings),
            name="codify-workspace-cleanup",
        )
        self._workspace_cleanup_task = cleanup_task

        def cleanup_done(task: asyncio.Task) -> None:
            if self._workspace_cleanup_task is task:
                self._workspace_cleanup_task = None
            if task.cancelled():
                return
            try:
                task.result()
            except Exception:  # noqa: BLE001
                logger.exception("Workspace cleanup background task failed")

        cleanup_task.add_done_callback(cleanup_done)

    async def _run_workspace_cleanup(self, settings) -> None:
        """Run one workspace cleanup batch in a session owned by the background task."""
        async with AsyncSessionLocal() as db:
            await self._cleanup_workspace_batch(db, settings)

    async def _maybe_cleanup_retained_containers(self, db: AsyncSession) -> None:
        """Start bounded terminal-container reconciliation without blocking scheduling."""
        del db
        now = time.time()
        if (
            now - self._last_retained_container_cleanup_at
            < _RETAINED_CONTAINER_CLEANUP_INTERVAL_SECONDS
        ):
            return
        if (
            self._retained_container_cleanup_task is not None
            and not self._retained_container_cleanup_task.done()
        ):
            return

        self._last_retained_container_cleanup_at = now
        cleanup_task = asyncio.create_task(
            self._run_retained_container_cleanup(get_settings()),
            name="codify-retained-container-cleanup",
        )
        self._retained_container_cleanup_task = cleanup_task

        def cleanup_done(task: asyncio.Task) -> None:
            if self._retained_container_cleanup_task is task:
                self._retained_container_cleanup_task = None
            if task.cancelled():
                return
            try:
                task.result()
            except Exception:  # noqa: BLE001
                logger.exception("Retained container cleanup background task failed")

        cleanup_task.add_done_callback(cleanup_done)

    async def _run_retained_container_cleanup(self, settings) -> None:
        async with AsyncSessionLocal() as db:
            await self._cleanup_retained_container_batch(db, settings)

    async def _cleanup_retained_container_batch(self, db: AsyncSession, settings) -> None:
        """Finalize logs and reap terminal task containers left by transient failures."""
        terminal_statuses = (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )
        active_worker_ids = {
            task_id
            for task_id, handle in self._worker_tasks.items()
            if not handle.done()
        }
        candidate_stmt = (
            select(Task.id)
            .where(
                Task.status.in_(terminal_statuses),
                Task.container_id.is_not(None),
            )
            .order_by(Task.updated_at.asc(), Task.id.asc())
            .limit(_RETAINED_CONTAINER_CLEANUP_BATCH_SIZE)
        )
        if active_worker_ids:
            candidate_stmt = candidate_stmt.where(Task.id.not_in(active_worker_ids))
        candidate_ids = list((await db.execute(candidate_stmt)).scalars().all())

        finalized = 0
        removed = 0
        deferred = 0
        for task_id in candidate_ids:
            handle = self._worker_tasks.get(task_id)
            if handle is not None and not handle.done():
                continue
            task = (
                await db.execute(
                    select(Task)
                    .where(
                        Task.id == task_id,
                        Task.status.in_(terminal_statuses),
                        Task.container_id.is_not(None),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if task is None:
                await db.rollback()
                continue
            container_reference = task.container_id
            try:
                docker, container, _connection = await find_task_container(
                    db,
                    task,
                    settings,
                    container_reference,
                )
            except TaskContainerNotFoundError:
                task.raw_logs_finalized_at = (
                    getattr(task, "raw_logs_finalized_at", None) or utcnow()
                )
                await self._clear_retained_container_reference(db, task)
                finalized += 1
                continue
            except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
                deferred += 1
                await db.rollback()
                logger.debug(
                    "Retained container cleanup deferred for task %s: %s",
                    task_id,
                    exc,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                deferred += 1
                await db.rollback()
                logger.warning(
                    "Retained container lookup failed for task %s: %s",
                    task_id,
                    exc,
                )
                continue

            try:
                await asyncio.to_thread(container.reload)
            except NotFound:
                task.raw_logs_finalized_at = (
                    getattr(task, "raw_logs_finalized_at", None) or utcnow()
                )
                await self._clear_retained_container_reference(db, task)
                finalized += 1
                continue
            except Exception as exc:  # noqa: BLE001
                deferred += 1
                await db.rollback()
                logger.warning(
                    "Could not inspect retained container %s for task %s: %s",
                    container_reference,
                    task_id,
                    exc,
                )
                continue

            if getattr(container, "status", None) not in _QUIESCENT_CONTAINER_STATUSES:
                try:
                    await _stop_recovered_cancelled_container(container, task_id)
                except Exception as exc:  # noqa: BLE001
                    deferred += 1
                    await db.rollback()
                    logger.warning(
                        "Could not stop retained container %s for task %s: %s",
                        container_reference,
                        task_id,
                        exc,
                    )
                    continue

            if task.raw_logs_finalized_at is None:
                try:
                    raw_console_log = await asyncio.to_thread(
                        docker.read_file_from_container,
                        container,
                        "/tmp/codify-runtime/console.log",
                    )
                except Exception:  # noqa: BLE001
                    raw_console_log = None
                if not isinstance(raw_console_log, bytes):
                    try:
                        raw_console_log = await asyncio.to_thread(
                            docker.get_container_logs,
                            container,
                        )
                    except Exception as exc:  # noqa: BLE001
                        deferred += 1
                        await db.rollback()
                        logger.warning(
                            "Could not finalize retained task %s raw logs: %s",
                            task_id,
                            exc,
                        )
                        continue
                if not isinstance(raw_console_log, bytes):
                    deferred += 1
                    await db.rollback()
                    continue
                await persist_raw_log_snapshot(
                    db,
                    task_id=task.id,
                    content=raw_console_log,
                )
                task.raw_logs_finalized_at = utcnow()
                await db.commit()
                finalized += 1

            try:
                await asyncio.to_thread(container.remove, force=True, v=True)
            except Exception as exc:  # noqa: BLE001
                deferred += 1
                await db.rollback()
                logger.warning(
                    "Could not remove retained container %s for task %s: %s",
                    container_reference,
                    task_id,
                    exc,
                )
                continue
            await self._clear_retained_container_reference(db, task)
            removed += 1

        if candidate_ids:
            logger.info(
                "Retained container cleanup finalized %s task(s), removed %s "
                "container(s), deferred %s",
                finalized,
                removed,
                deferred,
            )

    async def _cleanup_workspace_batch(self, db: AsyncSession, settings) -> None:
        """Delete stale workspaces, locking and committing one Issue at a time."""
        root = str(settings.worker_workspace_host_path).strip()
        retention_days = settings.worker_workspace_retention_days

        cutoff = utcnow() - timedelta(days=retention_days)
        active_task_exists = (
            select(Task.id)
            .where(
                Task.issue_id == Issue.id,
                or_(
                    Task.status.in_(
                        (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
                    ),
                    Task.container_id.is_not(None),
                ),
            )
            .exists()
        )
        candidate_ids = list(
            (
                await db.execute(
                    select(Issue.id)
                    .where(
                        func.coalesce(Issue.workspace_last_used_at, Issue.created_at) < cutoff,
                        Issue.workspace_deleted_at.is_(None),
                        ~active_task_exists,
                    )
                    .order_by(
                        Issue.workspace_delete_attempted_at.asc().nulls_first(),
                        Issue.id.asc(),
                    )
                    .limit(_WORKSPACE_CLEANUP_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
        removed_issue_workspaces = 0
        failed_issue_workspaces = 0
        checked_issue_workspaces = 0
        for issue_id in candidate_ids:
            # Task creation takes the same row lock. Re-checking after acquisition
            # prevents a task created after the candidate scan from losing its workspace.
            issue = (
                await db.execute(
                    select(Issue)
                    .where(
                        Issue.id == issue_id,
                        func.coalesce(Issue.workspace_last_used_at, Issue.created_at) < cutoff,
                        Issue.workspace_deleted_at.is_(None),
                        ~active_task_exists,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if issue is None:
                await db.rollback()
                continue
            checked_issue_workspaces += 1
            attempted_at = utcnow()
            try:
                if await remove_issue_workspace_remote(db, settings, issue):
                    removed_issue_workspaces += 1
                issue.workspace_delete_attempted_at = attempted_at
                issue.workspace_deleted_at = attempted_at
                issue.workspace_delete_error = None
            except Exception as exc:  # noqa: BLE001
                failed_issue_workspaces += 1
                issue.workspace_delete_attempted_at = attempted_at
                issue.workspace_delete_error = str(exc)[:4000]
                logger.warning(
                    "Failed to clean issue %s workspace on worker %s: %s",
                    issue.id,
                    issue.worker_profile_id,
                    exc,
                )
            await db.commit()

        removed_ci_bundles = await asyncio.to_thread(
            cleanup_expired_ci_failure_bundles,
            root,
            retention_days=retention_days,
        )
        if candidate_ids or removed_ci_bundles:
            logger.info(
                "Workspace cleanup checked %s issue(s), removed %s workspace(s), "
                "failed %s, and removed %s CI bundle(s)",
                checked_issue_workspaces,
                removed_issue_workspaces,
                failed_issue_workspaces,
                removed_ci_bundles,
            )

    async def _maybe_cleanup_issue_locks(self, db: AsyncSession) -> None:
        """Periodically delete locks for completed/failed/cancelled tasks."""
        now = time.time()
        if now - self._last_lock_cleanup_at < _LOCK_CLEANUP_INTERVAL_SECONDS:
            return

        removed = await cleanup_inactive_issue_execution_locks(db)
        if removed:
            await db.commit()
            logger.warning("Cleaned up %s inactive issue execution lock(s)", removed)
        self._last_lock_cleanup_at = now

    async def _mark_eligible_as_queued(self, db: AsyncSession) -> None:
        """Promote only the legal active head of each Issue to QUEUED (spec §6.4).

        Order per cycle: (1) repair Issues that carry an active NULL sequence under
        the Issue row lock (fail-closed keeps the Issue non-runnable when
        unrecoverable); (2) normalize illegal historical ``QUEUED`` rows (active
        NULL / active predecessor) back to ``PENDING``; (3) promote the due head
        of each unlocked Issue from ``PENDING`` to ``QUEUED``.
        """
        now = utcnow()
        await self._repair_active_null_sequence_issues(db)
        await self._normalize_illegal_queued_tasks(db)
        await self._promote_due_heads(db, now)

    async def _repair_active_null_sequence_issues(self, db: AsyncSession) -> None:
        """Repair Issues with an active NULL ``issue_sequence`` under the Issue lock."""
        null_issue_result = await db.execute(
            select(Task.issue_id)
            .distinct()
            .where(
                Task.status.in_(ACTIVE_STATUS_VALUES),
                Task.issue_sequence.is_(None),
            )
        )
        null_issue_ids = [
            row[0] for row in null_issue_result.fetchall() if row[0] is not None
        ]
        for issue_id in null_issue_ids:
            try:
                await db.execute(
                    select(Issue).where(Issue.id == issue_id).with_for_update()
                )
                report = await ensure_issue_order_integrity_locked(
                    db,
                    issue_id=issue_id,
                    repair_nulls=True,
                )
                if report["repaired_sequences"] or report["repaired_projections"]:
                    self._emit_event(
                        "issue_sequence_repaired",
                        reason="backfilled_null_sequence",
                        issue_id=issue_id,
                        repaired_sequences=report["repaired_sequences"],
                        repaired_projections=report["repaired_projections"],
                    )
                await db.commit()
            except IssueOrderIntegrityError as exc:
                await db.rollback()
                self._emit_event(
                    "issue_sequence_integrity_failed",
                    reason=exc.reason,
                    issue_id=issue_id,
                )
                logger.warning("Issue %s non-runnable: %s", issue_id, exc.reason)

    async def _normalize_illegal_queued_tasks(self, db: AsyncSession) -> None:
        """Demote historical ``QUEUED`` tasks that are not the legal head back to PENDING."""
        task_alias = aliased(Task)
        result = await db.execute(
            update(Task)
            .where(
                Task.status == TaskStatus.QUEUED,
                or_(
                    Task.issue_sequence.is_(None),
                    exists(
                        select(1).where(
                            task_alias.issue_id == Task.issue_id,
                            task_alias.status.in_(ACTIVE_STATUSES),
                            task_alias.issue_sequence.is_(None),
                        )
                    ),
                    exists(
                        select(1).where(
                            task_alias.issue_id == Task.issue_id,
                            task_alias.status.in_(ACTIVE_STATUSES),
                            task_alias.issue_sequence.is_not(None),
                            task_alias.issue_sequence < Task.issue_sequence,
                        )
                    ),
                ),
            )
            .values(status=TaskStatus.PENDING)
        )
        if result.rowcount > 0:
            await db.commit()
            logger.warning(
                "Normalized %s illegal QUEUED task(s) back to PENDING",
                result.rowcount,
            )

    async def _promote_due_heads(self, db: AsyncSession, now: datetime) -> None:
        """Promote the due active head of each unlocked Issue from PENDING to QUEUED."""
        task_alias = aliased(Task)
        blocked_issue_ids = list(self._running_issues) if self._running_issues else []

        stmt = (
            update(Task)
            .where(
                Task.status == TaskStatus.PENDING,
                Task.issue_sequence.is_not(None),
                (Task.scheduled_at.is_(None)) | (Task.scheduled_at <= now),
                ~exists(
                    select(1).where(
                        task_alias.issue_id == Task.issue_id,
                        task_alias.status.in_(ACTIVE_STATUSES),
                        task_alias.issue_sequence.is_(None),
                    )
                ),
                ~exists(
                    select(1).where(
                        task_alias.issue_id == Task.issue_id,
                        task_alias.status.in_(ACTIVE_STATUSES),
                        task_alias.issue_sequence.is_not(None),
                        task_alias.issue_sequence < Task.issue_sequence,
                    )
                ),
                ~exists(
                    select(1).where(IssueExecutionLock.issue_id == Task.issue_id)
                ),
                # A PENDING task whose frozen Kit locator is known unavailable
                # stays PENDING: promotion would only queue a run that must be
                # parked again (§13.2).
                ~exists(
                    select(1).where(
                        TaskWorkerProfileSnapshot.task_id == Task.id,
                        TaskWorkerProfileSnapshot.runtime_locator_fingerprint.is_not(None),
                        TaskWorkerProfileSnapshot.runtime_locator_fingerprint
                        == WorkerRuntimeReadiness.runtime_locator_fingerprint,
                        WorkerRuntimeReadiness.status == READINESS_UNAVAILABLE,
                    )
                ),
            )
            .values(status=TaskStatus.QUEUED)
        )
        if blocked_issue_ids:
            stmt = stmt.where(
                (Task.issue_id.is_(None)) | (~Task.issue_id.in_(blocked_issue_ids))
            )
        result = await db.execute(stmt)
        if result.rowcount > 0:
            await db.commit()
            logger.debug(f"Marked {result.rowcount} eligible task(s) as QUEUED")
            # Transition issues to in_progress for all newly queued tasks
            queued_issue_result = await db.execute(
                select(Task.issue_id)
                .where(
                    Task.status == TaskStatus.QUEUED,
                    Task.issue_id != None,
                )
                .distinct()
            )
            issue_ids = [row[0] for row in queued_issue_result]
            if issue_ids:
                await db.execute(
                    update(Issue)
                    .where(
                        Issue.id.in_(issue_ids),
                        Issue.status.in_([IssueStatus.OPEN.value, IssueStatus.IN_REVIEW.value]),
                    )
                    .values(status=IssueStatus.IN_PROGRESS.value)
                )
                await db.commit()
                logger.debug(
                    f"Transitioned {len(issue_ids)} issue(s) to IN_PROGRESS for queued tasks"
                )

    async def _get_running_count(self, db: AsyncSession) -> int:
        """Get count of currently running tasks."""
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING)
        )
        return result.scalar() or 0

    async def _get_next_task(self, db: AsyncSession) -> Task | None:
        """Get the next QUEUED legal head to execute based on priority.

        Only picks the legal active head of each Issue (spec §6.5): the query
        itself excludes active-NULL sequences and active predecessors so illegal
        historical ``QUEUED`` data can never be returned. This is only a
        candidate; the atomic claim re-verifies inside the Issue row lock.

        Ordering:
        1. priority ASC — P0(0) runs before P1(1) before P2(2)
        2. scheduled tasks before immediate — users who booked a slot
           have a reasonable expectation their task runs on time
        3. scheduled_at ASC — earlier due times first
        4. created_at ASC, id ASC — FIFO tiebreaker (§6.5)
        """
        task_alias = aliased(Task)
        stmt = select(Task).where(
            Task.status == TaskStatus.QUEUED,
            Task.issue_sequence.is_not(None),
            ~exists(
                select(1).where(
                    task_alias.issue_id == Task.issue_id,
                    task_alias.status.in_(ACTIVE_STATUSES),
                    task_alias.issue_sequence.is_(None),
                )
            ),
            ~exists(
                select(1).where(
                    task_alias.issue_id == Task.issue_id,
                    task_alias.status.in_(ACTIVE_STATUSES),
                    task_alias.issue_sequence.is_not(None),
                    task_alias.issue_sequence < Task.issue_sequence,
                )
            ),
            ~exists(
                select(1).where(IssueExecutionLock.issue_id == Task.issue_id)
            ),
        )
        if self._running_issues:
            # Filtering in SQL avoids a queued task for a busy Issue sitting at the
            # head of the priority order and starving runnable tasks from other Issues.
            stmt = stmt.where(Task.issue_id.not_in(self._running_issues))
        result = await db.execute(
            stmt.order_by(
                Task.priority.asc(),
                case((Task.scheduled_at.is_not(None), 0), else_=1),
                Task.scheduled_at.asc(),
                Task.created_at.asc(),
                Task.id.asc(),
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def _execute_task(self, db: AsyncSession, task: Task) -> None:
        """Execute a task in a separate thread, claiming it atomically (§6.6)."""
        task_id = task.id
        issue_id = task.issue_id
        logger.info("Executing task %s for issue %s", task_id, issue_id)

        # Runtime readiness gate (§13): a mounted-kit task must be confirmed
        # (ready via TTL or a successful deterministic first-probe) before a
        # worker container is created. A deterministic unavailable conclusion
        # fails the probed task and parks unclaimed same-fingerprint tasks.
        if await self._apply_runtime_readiness_gate(db, task):
            return

        # --- Atomic claim: one DB transaction ------------------------------
        # Lock the Issue row first (never the reverse order), re-verify ordering
        # integrity, re-load the Task FOR UPDATE, confirm it is the due legal
        # head, acquire the IssueExecutionLock (ON CONFLICT DO NOTHING) and CAS
        # QUEUED→RUNNING. Only after the commit succeeds do we start the worker.
        try:
            await db.execute(
                select(Issue).where(Issue.id == issue_id).with_for_update()
            )
            await ensure_issue_order_integrity_locked(
                db,
                issue_id=issue_id,
                repair_nulls=True,
            )
        except IssueOrderIntegrityError as exc:
            await db.rollback()
            self._emit_event(
                "issue_task_claim_rejected",
                reason="sequence_repair_required",
                issue_id=issue_id,
                task_id=task_id,
            )
            logger.warning(
                "Issue %s blocked from claiming task %s: %s",
                issue_id,
                task_id,
                exc.reason,
            )
            return

        task = (
            await db.execute(
                select(Task)
                .where(Task.id == task_id)
                .with_for_update()
                # _get_next_task already loaded this row into the session identity
                # map; without populate_existing the FOR UPDATE re-read returns the
                # stale in-memory object and the CAS below can claim a task a
                # concurrent cancel already committed as CANCELLED (§6.6).
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if task is None:
            await db.rollback()
            return

        if task.status != TaskStatus.QUEUED:
            # rollback() expires the task's attributes, so snapshot the status
            # now; reading it in the log line below would otherwise attempt a
            # synchronous lazy load and raise MissingGreenlet in an AsyncSession.
            current_status = task.status
            await db.rollback()
            self._emit_event(
                "issue_task_claim_rejected",
                reason="task_state_changed",
                issue_id=issue_id,
                task_id=task_id,
            )
            logger.warning(
                "Task %s no longer QUEUED (status=%s); skipping claim",
                task_id,
                current_status.value,
            )
            return

        if task.issue_sequence is None:
            await self._demote_queued_task(db, task, "sequence_repair_required")
            return
        if task.scheduled_at is not None and task.scheduled_at > utcnow():
            await self._demote_queued_task(db, task, "schedule_not_due")
            return
        if await self._has_active_predecessor(db, task):
            await self._demote_queued_task(db, task, "predecessor_active")
            return

        # Usage limits are enforced before acquiring the lock so an over-limit
        # task fails without an ownership-release dance.
        initiator_user_id = getattr(task, "initiator_user_id", None)
        if isinstance(initiator_user_id, int):
            try:
                await get_usage_quota_service().raise_if_over_limit(
                    db,
                    initiator_user_id,
                    scope="execute",
                )
            except UsageLimitExceeded as exc:
                logger.info(
                    "Task %s blocked by usage limits before execution",
                    task_id,
                )
                task.status = TaskStatus.FAILED
                task.error_message = json.dumps(usage_limit_exceeded_detail(exc))
                task.completed_at = utcnow()
                task.raw_logs_finalized_at = (
                    getattr(task, "raw_logs_finalized_at", None) or utcnow()
                )
                await db.commit()
                await maybe_update_issue_status(db, issue_id)
                return

        if not await acquire_issue_execution_lock(db, task):
            await db.rollback()
            self._emit_event(
                "issue_task_claim_rejected",
                reason="issue_locked",
                issue_id=issue_id,
                task_id=task_id,
            )
            logger.debug("Issue %s locked; task %s remains queued", issue_id, task_id)
            return

        # CAS QUEUED → RUNNING in the same transaction as the lock insert.
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        try:
            await db.commit()
        except Exception as e:  # noqa: BLE001
            # The lock insert and the RUNNING update share one transaction: a
            # failed commit persists neither, so there is no lock to release.
            await db.rollback()
            logger.exception("Failed to atomically claim task %s: %s", task_id, e)
            return

        # Track in memory AFTER the DB commit so _reconcile_running_state
        # (which queries for RUNNING tasks) doesn't race with the update.
        self._running_tasks.add(task_id)
        self._running_issues.add(issue_id)

        # Any active task means the issue is currently in progress.
        await self._transition_issue_to_in_progress(db, issue_id)

        # Execute via worker in a thread pool WITHOUT waiting
        self._worker_tasks[task_id] = asyncio.create_task(self._run_task_background(task_id))
        logger.info("Task %s submitted to thread pool", task_id)

    async def _has_active_predecessor(self, db: AsyncSession, task: Task) -> bool:
        """Return True when an active Task with a smaller sequence exists."""
        task_alias = aliased(Task)
        result = await db.execute(
            select(task_alias.id)
            .where(
                task_alias.issue_id == task.issue_id,
                task_alias.status.in_(ACTIVE_STATUSES),
                task_alias.issue_sequence.is_not(None),
                task_alias.issue_sequence < task.issue_sequence,
            )
            .limit(1)
        )
        return result.first() is not None

    async def _apply_runtime_readiness_gate(self, db: AsyncSession, task: Task) -> bool:
        """Run the pre-execution runtime readiness gate (§13).

        Returns True when the task must not be claimed this cycle (it was failed
        or parked), False when execution may proceed.
        """
        snapshot = await self._load_task_snapshot(db, task.id)
        fingerprint = (
            getattr(snapshot, "runtime_locator_fingerprint", None)
            if snapshot is not None
            else None
        )
        if not fingerprint:
            # baked-image target (or a pre-071 legacy snapshot): no host Kit to
            # locate, so no readiness gate applies.
            return False
        readiness = await read_runtime_readiness(db, fingerprint)
        if readiness.is_ready:
            return False
        if readiness.is_unavailable:
            await self._park_tasks_for_unavailable_runtime(db, task, fingerprint, readiness)
            return True
        # unknown / expired ready → deterministic first-probe (§13.4).
        settings = get_settings()
        connection = connection_from_snapshot(snapshot, settings)
        try:
            outcome = await run_deterministic_kit_probe(
                db,
                connection=connection,
                image=snapshot.image,
                runtime_mode=snapshot.runtime_mode,
                worker_kit_version=snapshot.worker_kit_version or "",
                worker_kit_path=snapshot.worker_kit_path or "",
                ttl_seconds=settings.worker_runtime_readiness_ttl_seconds,
            )
        except RuntimeProbeTransientError as exc:
            # No new conclusion (§13.5): leave the task QUEUED and retry next
            # cycle rather than run a worker container against an unverified Kit.
            self._emit_event(
                "runtime_readiness_probe_transient",
                reason="probe_transient",
                issue_id=task.issue_id,
                task_id=task.id,
                message=str(exc)[:500],
            )
            return True
        if outcome.is_ready:
            return False
        if outcome.is_unavailable:
            if outcome.committed:
                # Deterministic unavailable conclusion from a live probe that
                # this probe committed: fail the probed task and park unclaimed
                # same-fingerprint tasks (§13.4).
                await self._fail_task_for_runtime_check(db, task, outcome.readiness)
                await self._park_other_queued_tasks(
                    db, task, fingerprint, outcome.readiness
                )
            else:
                # The probe was superseded by a concurrent check that concluded
                # unavailable (§13.3 CAS). §13.3/§13.5: a late probe must not
                # fail the current task — park it back to PENDING so it recovers
                # once the Kit becomes available instead of requiring a manual
                # retry (§24.13).
                await self._park_tasks_for_unavailable_runtime(
                    db, task, fingerprint, outcome.readiness
                )
            return True
        # unknown: the probe result was superseded by a concurrent check or no
        # conclusion is stored yet (§13.3/§19). A late/superseded generation
        # must never change readiness or Task state, so leave the Task QUEUED
        # and re-evaluate next cycle instead of failing it.
        return True

    async def _load_task_snapshot(
        self,
        db: AsyncSession,
        task_id: int,
    ) -> TaskWorkerProfileSnapshot | None:
        result = await db.execute(
            select(TaskWorkerProfileSnapshot).where(
                TaskWorkerProfileSnapshot.task_id == task_id
            )
        )
        return result.scalar_one_or_none()

    async def _park_tasks_for_unavailable_runtime(
        self,
        db: AsyncSession,
        task: Task,
        fingerprint: str,
        readiness: RuntimeReadiness,
    ) -> None:
        """Demote the current and unclaimed same-fingerprint QUEUED Tasks to PENDING."""
        await self._park_queued_task(db, task, readiness)
        await self._park_other_queued_tasks(db, task, fingerprint, readiness)

    async def _park_other_queued_tasks(
        self,
        db: AsyncSession,
        task: Task,
        fingerprint: str,
        readiness: RuntimeReadiness,
    ) -> None:
        """Return every unclaimed QUEUED Task sharing the fingerprint to PENDING."""
        result = await db.execute(
            select(Task).where(
                Task.status == TaskStatus.QUEUED,
                Task.id != task.id,
                Task.issue_id.is_not(None),
                Task.id.in_(
                    select(TaskWorkerProfileSnapshot.task_id).where(
                        TaskWorkerProfileSnapshot.runtime_locator_fingerprint == fingerprint,
                    )
                ),
            )
        )
        for other in result.scalars().all():
            await self._park_queued_task(db, other, readiness)

    async def _park_queued_task(self, db: AsyncSession, task: Task, readiness: RuntimeReadiness) -> None:
        """Return one QUEUED Task to PENDING because its runtime is unavailable."""
        if task.status != TaskStatus.QUEUED:
            return
        task.status = TaskStatus.PENDING
        await db.commit()
        self._emit_event(
            "runtime_unavailable_task_parked",
            reason="worker_runtime_unavailable",
            issue_id=task.issue_id,
            task_id=task.id,
            issue_sequence=task.issue_sequence,
            failure_code=readiness.failure_code,
            failure_message=(readiness.failure_message or "")[:500],
        )
        logger.warning(
            "Task %s returned to PENDING (worker_runtime_unavailable)",
            task.id,
        )

    async def _fail_task_for_runtime_check(
        self,
        db: AsyncSession,
        task: Task,
        readiness: RuntimeReadiness,
    ) -> None:
        """Fail the probed task when the live Kit probe is deterministically unavailable."""
        task.status = TaskStatus.FAILED
        task.error_message = json.dumps(
            {
                "code": "worker_runtime_check_failed",
                "message": "Worker Kit runtime check failed",
                "failure_code": readiness.failure_code,
                "failure_message": readiness.failure_message,
            },
            ensure_ascii=False,
        )
        task.completed_at = utcnow()
        task.raw_logs_finalized_at = (
            getattr(task, "raw_logs_finalized_at", None) or utcnow()
        )
        await db.commit()
        self._emit_event(
            "runtime_readiness_check_failed",
            reason=readiness.failure_code or "worker_runtime_check_failed",
            issue_id=task.issue_id,
            task_id=task.id,
            issue_sequence=task.issue_sequence,
            failure_message=(readiness.failure_message or "")[:500],
        )
        logger.warning(
            "Task %s failed worker runtime check (%s)",
            task.id,
            readiness.failure_code,
        )
        await maybe_update_issue_status(db, task.issue_id)

    async def _demote_queued_task(
        self,
        db: AsyncSession,
        task: Task,
        reason: str,
    ) -> None:
        """Return an illegal QUEUED Task to PENDING (spec §6.6)."""
        task.status = TaskStatus.PENDING
        await db.commit()
        self._emit_event(
            "issue_queue_invalid_queued_normalized",
            reason=reason,
            issue_id=task.issue_id,
            task_id=task.id,
            issue_sequence=task.issue_sequence,
        )
        logger.warning(
            "Demoted task %s to PENDING (reason=%s)",
            task.id,
            reason,
        )

    async def _transition_issue_to_in_progress(self, db: AsyncSession, issue_id: int) -> None:
        """Auto-transition issue OPEN/COMPLETED → IN_PROGRESS when a task starts running."""
        try:
            issue = await db.get(Issue, issue_id)
            if issue and issue.status in (IssueStatus.OPEN.value, IssueStatus.IN_REVIEW.value):
                issue.status = IssueStatus.IN_PROGRESS.value
                await db.commit()
                logger.info(f"Issue {issue_id} auto-transitioned to IN_PROGRESS")
        except Exception as e:
            logger.warning(f"Failed to transition issue {issue_id}: {e}")

    async def _run_task_background(self, task_id: int) -> None:
        """Run task in background thread pool."""
        self._active_worker_threads += 1
        defer_recovery = False
        t_submit = time.time()
        logger.info(
            f"Task {task_id} submitted to thread pool "
            f"(active_threads={self._active_worker_threads}, "
            f"max_workers={_worker_executor._max_workers})"
        )
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_task,
                task_id,
            )
            elapsed = time.time() - t_submit
            if success:
                logger.info(
                    f"Task {task_id} completed successfully (total={elapsed:.0f}s, "
                    f"active_threads={self._active_worker_threads})"
                )
            else:
                logger.error(
                    f"Task {task_id} failed (total={elapsed:.0f}s, "
                    f"active_threads={self._active_worker_threads})"
                )

        except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
            defer_recovery = True
            logger.warning(
                "Task %s lost a conclusive Docker view during startup; returning it "
                "to deferred recovery: %s",
                task_id,
                exc,
            )
        except Exception as exc:
            logger.exception(f"Task {task_id} failed with exception in background")
            await self._mark_worker_bootstrap_failed(task_id, exc)

        finally:
            self._active_worker_threads -= 1
            if defer_recovery:
                recovery_task = asyncio.create_task(
                    self._coordinate_unavailable_recovery(task_id)
                )
                self._worker_tasks[task_id] = recovery_task
                self._terminal_worker_seen_at.pop(task_id, None)
                logger.info(
                    "Deferred recovery coordinator started for task %s after startup lookup",
                    task_id,
                )
            else:
                # Clean up tracking
                self._worker_tasks.pop(task_id, None)
                self._terminal_worker_seen_at.pop(task_id, None)
                self._running_tasks.discard(task_id)
                try:
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(select(Task).where(Task.id == task_id))
                        task = result.scalar_one_or_none()
                        if task:
                            # Guard: only release the DB lock and in-memory slot if WE still hold it.
                            # If _reconcile_running_state already cleared us and a replacement task
                            # re-acquired the lock for this issue, releasing here would corrupt the
                            # new task's execution slot.
                            lock_result = await db.execute(
                                select(IssueExecutionLock).where(
                                    IssueExecutionLock.issue_id == task.issue_id
                                )
                            )
                            lock = lock_result.scalar_one_or_none()
                            if lock is None or lock.task_id == task_id:
                                if self._block_issue_for_retained_container(task):
                                    logger.warning(
                                        "Keeping Issue %s locked because terminal task %s "
                                        "retains container %s",
                                        task.issue_id,
                                        task_id,
                                        task.container_id,
                                    )
                                else:
                                    self._running_issues.discard(task.issue_id)
                                    await self._release_issue_lock(
                                        db,
                                        issue_id=task.issue_id,
                                        owner_task_id=task_id,
                                    )
                                    await db.commit()
                                    # Auto-transition issue to COMPLETED if all tasks done
                                    await self._maybe_complete_issue(db, task.issue_id)
                except Exception:
                    logger.exception("Failed to release lock for task %s", task_id)

    async def _mark_worker_bootstrap_failed(self, task_id: int, exc: Exception) -> None:
        """Persist failures that happen before WorkerExecutor can own task state."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Task).where(Task.id == task_id))
                task = result.scalar_one_or_none()
                if task is None or task.status != TaskStatus.RUNNING:
                    return

                from app.core.worker import sanitize_sensitive_data

                cancellation_requested = isinstance(
                    getattr(task, "cancel_requested_at", None),
                    datetime,
                )
                task.status = TaskStatus.CANCELLED if cancellation_requested else TaskStatus.FAILED
                task.error_message = (
                    "Cancelled by user before worker startup completed"
                    if cancellation_requested
                    else sanitize_sensitive_data(f"Worker failed to start: {exc}")[:2000]
                )
                task.completed_at = utcnow()
                if getattr(task, "container_id", None) is None:
                    task.raw_logs_finalized_at = (
                        getattr(task, "raw_logs_finalized_at", None) or utcnow()
                    )
                if self._block_issue_for_retained_container(task):
                    logger.warning(
                        "Keeping Issue %s locked after worker bootstrap failure because "
                        "task %s retains container %s",
                        task.issue_id,
                        task.id,
                        task.container_id,
                    )
                else:
                    await self._release_issue_lock(
                        db,
                        issue_id=task.issue_id,
                        owner_task_id=task.id,
                    )
                    self._running_issues.discard(task.issue_id)
                await db.commit()
        except Exception:
            logger.exception("Failed to persist worker bootstrap failure for task %s", task_id)

    async def _maybe_complete_issue(self, db: AsyncSession, issue_id: int) -> None:
        """Delegate to shared helper."""
        await maybe_update_issue_status(db, issue_id)

    async def _crash_recovery(self) -> None:
        """Recover from crashes: clean up orphan containers, resume legitimate ones.

        Handles several scenarios:
        - Container running + task RUNNING → resume monitoring
        - Container exited + task RUNNING → resume (collects logs/results from exited container)
        - Container running/exited + no matching task → remove (true orphan)
        - Task RUNNING + no container → mark FAILED
        """
        logger.info("Running crash recovery...")

        async with AsyncSessionLocal() as db:
            removed_locks = await cleanup_inactive_issue_execution_locks(db)
            if removed_locks:
                logger.warning("Cleaned up %s inactive issue execution lock(s)", removed_locks)

            # Running tasks must be resumed. Any terminal task with a durable
            # container reference must either retain it for raw-log finalization or
            # have the stale/failed-cleanup reference reconciled before data cleanup.
            result = await db.execute(
                select(Task).where(
                    or_(
                        Task.status == TaskStatus.RUNNING,
                        Task.container_id.is_not(None),
                    )
                )
            )
            owned_tasks = result.scalars().all()
            stuck_tasks = [
                task
                for task in owned_tasks
                if getattr(task.status, "value", task.status) == TaskStatus.RUNNING.value
            ]
            retained_task_ids = {
                task.id
                for task in owned_tasks
                if getattr(task.status, "value", task.status) != TaskStatus.RUNNING.value
                and getattr(task, "raw_logs_finalized_at", None) is None
            }
            finalized_reference_tasks = [
                task
                for task in owned_tasks
                if getattr(task.status, "value", task.status) != TaskStatus.RUNNING.value
                and getattr(task, "raw_logs_finalized_at", None) is not None
            ]
            running_task_ids = {task.id for task in stuck_tasks}
            if stuck_tasks:
                logger.warning(f"Found {len(stuck_tasks)} tasks in RUNNING status")

            settings = get_settings()

            # HARNESS_EXECUTION_MODE=v2_only: idempotently terminalize any
            # residual legacy V1 contract before resuming/counting anything
            # (open-harness-v2-phase1-design §2.3). Removes the affected tasks
            # from the recovery sets so they are never resumed.
            if settings.harness_execution_mode == "v2_only":
                legacy_ids = await self._remediate_legacy_contracts(db)
                if legacy_ids:
                    owned_tasks = [t for t in owned_tasks if t.id not in legacy_ids]
                    stuck_tasks = [t for t in stuck_tasks if t.id not in legacy_ids]
                    running_task_ids.difference_update(legacy_ids)

            targets = await list_known_docker_targets(db, settings, include_retained=True)
            task_connections = {
                task.id: await connection_for_task(db, task, settings) for task in owned_tasks
            }
            task_daemon_keys = {
                task_id: docker_daemon_key(connection)
                for task_id, connection in task_connections.items()
            }

            async def enumerate_target(target):
                has_running_tasks = any(
                    task_id in running_task_ids and daemon_key == target.daemon_key
                    for task_id, daemon_key in task_daemon_keys.items()
                )
                retry_offsets = (
                    _RECOVERY_RETRY_OFFSETS_SECONDS
                    if has_running_tasks
                    else _RECOVERY_RETRY_OFFSETS_SECONDS[:1]
                )
                started_at = asyncio.get_running_loop().time()
                last_error = None
                for retry_offset in retry_offsets:
                    delay = started_at + retry_offset - asyncio.get_running_loop().time()
                    if delay > 0:
                        await asyncio.sleep(delay)

                    async def try_connections():
                        nonlocal last_error
                        for connection in target.connections:
                            try:
                                containers = await asyncio.to_thread(
                                    _list_recovery_containers,
                                    connection,
                                    settings.worker_container_prefix,
                                )
                                return containers, connection
                            except Exception as exc:  # noqa: BLE001
                                last_error = exc
                                logger.warning(
                                    "Failed to enumerate Docker target %s: %s",
                                    connection.host,
                                    exc,
                                )
                        if last_error is not None:
                            raise last_error
                        return [], None

                    try:
                        containers, successful_connection = await asyncio.wait_for(
                            try_connections(),
                            timeout=_RECOVERY_PROBE_TIMEOUT_SECONDS,
                        )
                        return target, containers, successful_connection, None
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                return target, [], None, last_error

            target_results = await asyncio.gather(*(enumerate_target(target) for target in targets))
            resumed_task_ids: set[int] = {
                task.id
                for task in stuck_tasks
                if (handle := self._worker_tasks.get(task.id)) is not None and not handle.done()
            }
            for task in stuck_tasks:
                if task.id not in resumed_task_ids:
                    continue
                self._running_tasks.add(task.id)
                self._running_issues.add(task.issue_id)
                logger.info(
                    "Task %s is already owned by a local recovery worker; skipping duplicate resume",
                    task.id,
                )
            unavailable_task_ids: set[int] = set()
            successful_connections: dict[str, DockerConnectionConfig] = {}
            pattern = _get_container_pattern()
            for target, all_containers, successful_connection, target_error in target_results:
                target_owned_task_ids = {
                    task_id
                    for task_id, daemon_key in task_daemon_keys.items()
                    if daemon_key == target.daemon_key
                }
                if target_error is not None:
                    unavailable_task_ids.update(target_owned_task_ids & running_task_ids)
                    logger.warning(
                        "Deferring recovery for tasks %s because Docker daemon %s "
                        "remains unreachable",
                        sorted(target_owned_task_ids & running_task_ids),
                        target.connection.host,
                    )
                    continue
                if successful_connection is not None:
                    successful_connections[target.daemon_key] = successful_connection
                for container in all_containers:
                    if not pattern.match(container.name):
                        continue

                    task_id = _extract_task_id(container.name)
                    c_status = container.status

                    # Ownership is decided against the FULL set of DB-known running
                    # and retained tasks, not just the tasks this target "owns" by
                    # daemon key. One physical daemon can be reachable through several
                    # connection strings (e.g. unix socket + tcp) that normalize to
                    # different daemon keys; scanning it under one alias must never
                    # orphan the containers of tasks another alias owns.
                    if task_id is None:
                        logger.warning(
                            f"Removing {c_status} unowned container: {container.name} "
                            f"(target={target.connection.host})"
                        )
                        try:
                            container.remove(force=(c_status == "running"), v=True)
                        except Exception as e:
                            logger.warning(f"Failed to remove container {container.name}: {e}")
                        continue
                    if task_id in resumed_task_ids:
                        logger.info(
                            "Skipping container %s for task %s already resumed via "
                            "another Docker target",
                            container.name,
                            task_id,
                        )
                        continue
                    if task_id in running_task_ids:
                        if c_status in ("running", "exited"):
                            task = next(task for task in stuck_tasks if task.id == task_id)
                            cancellation_requested = isinstance(
                                getattr(task, "cancel_requested_at", None),
                                datetime,
                            )
                            if cancellation_requested and c_status == "running":
                                try:
                                    await _stop_recovered_cancelled_container(container, task_id)
                                except Exception as exc:  # noqa: BLE001
                                    unavailable_task_ids.add(task_id)
                                    logger.warning(
                                        "Deferring recovery for cancelled task %s because "
                                        "container %s could not be stopped: %s",
                                        task_id,
                                        container.name,
                                        exc,
                                    )
                                    continue
                            logger.info(
                                "Resuming task %s on %s (container %s, status=%s, issue_id=%s)",
                                task_id,
                                target.connection.host,
                                container.name,
                                c_status,
                                task.issue_id,
                            )
                            self._running_tasks.add(task_id)
                            self._running_issues.add(task.issue_id)
                            resumed_task_ids.add(task_id)
                            self._worker_tasks[task_id] = asyncio.create_task(
                                self._resume_task_background(
                                    task_id,
                                    container.name,
                                    successful_connection,
                                )
                            )
                        else:
                            unavailable_task_ids.add(task_id)
                            logger.warning(
                                "Deferring recovery for task %s container %s in status %s "
                                "until its raw logs can be finalized",
                                task_id,
                                container.name,
                                c_status,
                            )
                    elif task_id in retained_task_ids:
                        logger.info(
                            "Retaining owned container %s for task %s until raw logs finalize",
                            container.name,
                            task_id,
                        )
                    else:
                        logger.warning(
                            f"Removing {c_status} orphan container: {container.name} "
                            f"(task_id={task_id}, target={target.connection.host})"
                        )
                        try:
                            container.remove(force=(c_status == "running"), v=True)
                        except Exception as e:
                            logger.warning(f"Failed to remove container {container.name}: {e}")

            cleared_finalized_references = 0
            for task in finalized_reference_tasks:
                container_reference = getattr(task, "container_id", None)
                if not isinstance(container_reference, str) or not container_reference.strip():
                    continue
                daemon_key = task_daemon_keys[task.id]
                if daemon_key not in successful_connections:
                    logger.warning(
                        "Keeping finalized task %s container reference because Docker "
                        "daemon %s is unavailable",
                        task.id,
                        task_connections[task.id].host,
                    )
                    continue
                try:
                    _docker, container, _connection = await find_task_container(
                        db,
                        task,
                        settings,
                        container_reference,
                        known_targets=targets,
                    )
                except TaskContainerNotFoundError:
                    pass
                except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
                    logger.warning(
                        "Keeping finalized task %s container reference after inconclusive "
                        "lookup of %s: %s",
                        task.id,
                        container_reference,
                        exc,
                    )
                    continue
                else:
                    try:
                        await asyncio.to_thread(container.remove, force=True, v=True)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Keeping finalized task %s container reference because %s "
                            "could not be removed: %s",
                            task.id,
                            container_reference,
                            exc,
                        )
                        continue
                task.container_id = None
                cleared_finalized_references += 1
            if cleared_finalized_references:
                await db.commit()
                logger.info(
                    "Cleared %s finalized task container reference(s)",
                    cleared_finalized_references,
                )

            # Prefix-based enumeration is retained for orphan cleanup, but task recovery
            # uses the immutable container ID so a deployment-time prefix change cannot
            # make a live worker invisible.
            for task in stuck_tasks:
                container_id = getattr(task, "container_id", None)
                if (
                    task.id in resumed_task_ids
                    or task.id in unavailable_task_ids
                    or not isinstance(container_id, str)
                    or not container_id.strip()
                ):
                    continue
                daemon_key = task_daemon_keys[task.id]
                successful_connection = successful_connections.get(daemon_key)
                if successful_connection is None:
                    unavailable_task_ids.add(task.id)
                    continue
                try:
                    container_name, container_status = await asyncio.to_thread(
                        _inspect_recovery_container,
                        successful_connection,
                        container_id,
                    )
                except NotFound:
                    continue
                except Exception as exc:  # noqa: BLE001
                    unavailable_task_ids.add(task.id)
                    logger.warning(
                        "Deferring recovery for task %s because direct lookup of "
                        "container %s on %s was inconclusive: %s",
                        task.id,
                        container_id,
                        successful_connection.host,
                        exc,
                    )
                    continue

                if container_status in ("running", "exited"):
                    cancellation_requested = isinstance(
                        getattr(task, "cancel_requested_at", None),
                        datetime,
                    )
                    if cancellation_requested and container_status == "running":
                        try:
                            _docker, container, _connection = await find_task_container(
                                db,
                                task,
                                settings,
                                container_id,
                            )
                            await _stop_recovered_cancelled_container(container, task.id)
                        except Exception as exc:  # noqa: BLE001
                            unavailable_task_ids.add(task.id)
                            logger.warning(
                                "Deferring recovery for cancelled task %s because stable "
                                "container %s could not be stopped: %s",
                                task.id,
                                container_id,
                                exc,
                            )
                            continue
                    logger.info(
                        "Recovered task %s by stable container ID %s on %s (name=%s, status=%s)",
                        task.id,
                        container_id,
                        successful_connection.host,
                        container_name,
                        container_status,
                    )
                    self._running_tasks.add(task.id)
                    self._running_issues.add(task.issue_id)
                    resumed_task_ids.add(task.id)
                    self._worker_tasks[task.id] = asyncio.create_task(
                        self._resume_task_background(
                            task.id,
                            container_name,
                            successful_connection,
                        )
                    )
                else:
                    unavailable_task_ids.add(task.id)
                    logger.warning(
                        "Deferring task %s recovery cleanup for container %s in status %s",
                        task.id,
                        container_id,
                        container_status,
                    )

            for task in stuck_tasks:
                if task.id in resumed_task_ids:
                    continue
                if task.id in unavailable_task_ids:
                    self._running_tasks.add(task.id)
                    self._running_issues.add(task.issue_id)
                    self._worker_tasks[task.id] = asyncio.create_task(
                        self._coordinate_unavailable_recovery(task.id)
                    )
                    logger.warning(
                        "Task %s remains RUNNING with issue %s locked while Docker "
                        "recovery is retried in the background",
                        task.id,
                        task.issue_id,
                    )
                    continue
                cancellation_requested = isinstance(
                    getattr(task, "cancel_requested_at", None),
                    datetime,
                )
                task.status = TaskStatus.CANCELLED if cancellation_requested else TaskStatus.FAILED
                task.error_message = (
                    "Cancelled by user; worker container is confirmed absent"
                    if cancellation_requested
                    else "Task was running when scheduler restarted (container not found)"
                )
                task.container_id = None
                task.completed_at = utcnow()
                task.raw_logs_finalized_at = (
                    getattr(task, "raw_logs_finalized_at", None) or utcnow()
                )
                await self._release_issue_lock(
                    db,
                    issue_id=task.issue_id,
                    owner_task_id=task.id,
                )
                logger.warning(
                    "Marked task %s as %s after reachable Docker daemon confirmed "
                    "that its container is absent",
                    task.id,
                    task.status.value,
                )

            retained_issue_result = await db.execute(
                select(Task.issue_id)
                .distinct()
                .where(
                    Task.status.in_(
                        (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                    ),
                    Task.container_id.is_not(None),
                )
            )
            retained_issue_ids = {
                row[0] for row in retained_issue_result.fetchall() if row[0] is not None
            }
            if retained_issue_ids:
                # A terminal task can still own a running container after a crash or
                # failed cancellation. Do not schedule another task for the Issue until
                # the retained-container reconciler has stopped and removed it.
                self._retained_container_blocked_issues.update(retained_issue_ids)
                self._running_issues.update(retained_issue_ids)
                logger.warning(
                    "Blocked %s Issue(s) until retained worker containers are reconciled",
                    len(retained_issue_ids),
                )

            await db.commit()

        failed_count = sum(
            1
            for task in stuck_tasks
            if task.id not in resumed_task_ids and task.id not in unavailable_task_ids
        )
        logger.info(
            "Crash recovery complete: %s resumed, %s awaiting Docker, %s marked failed",
            len(resumed_task_ids),
            len(unavailable_task_ids),
            failed_count,
        )

    async def _coordinate_unavailable_recovery(self, task_id: int) -> None:
        """Keep an unknown remote worker owned until its daemon becomes reachable."""
        attempt = 0
        try:
            while self.running:
                resume_context: tuple[str, DockerConnectionConfig] | None = None
                should_retry = False
                async with AsyncSessionLocal() as db:
                    task = await db.get(Task, task_id)
                    if task is None:
                        logger.warning(
                            "Stopping deferred Docker recovery because task %s no longer exists",
                            task_id,
                        )
                        return
                    if task.status != TaskStatus.RUNNING:
                        logger.info(
                            "Stopping deferred Docker recovery for task %s because status is %s",
                            task_id,
                            getattr(task.status, "value", task.status),
                        )
                        self._running_tasks.discard(task_id)
                        self._running_issues.discard(task.issue_id)
                        return

                    settings = get_settings()
                    container_name = (
                        f"{settings.worker_container_prefix}-{task.id}-issue{task.issue_id}"
                    )
                    container_reference = task.container_id or container_name
                    attempt += 1
                    try:
                        docker, container, connection = await find_task_container(
                            db,
                            task,
                            settings,
                            container_reference,
                        )
                        await asyncio.to_thread(container.reload)
                    except TaskContainerNotFoundError:
                        await db.refresh(task)
                        if task.status != TaskStatus.RUNNING:
                            continue
                        cancellation_requested = isinstance(
                            getattr(task, "cancel_requested_at", None),
                            datetime,
                        )
                        task.status = (
                            TaskStatus.CANCELLED if cancellation_requested else TaskStatus.FAILED
                        )
                        task.error_message = (
                            "Cancelled by user; worker container is confirmed absent"
                            if cancellation_requested
                            else (
                                "Task was running when scheduler restarted; Docker later "
                                "became reachable and confirmed that its container is absent"
                            )
                        )
                        task.container_id = None
                        task.completed_at = utcnow()
                        task.raw_logs_finalized_at = (
                            getattr(task, "raw_logs_finalized_at", None) or utcnow()
                        )
                        await self._release_issue_lock(
                            db,
                            issue_id=task.issue_id,
                            owner_task_id=task.id,
                        )
                        await db.commit()
                        self._running_tasks.discard(task_id)
                        self._running_issues.discard(task.issue_id)
                        logger.error(
                            "Deferred recovery marked task %s %s after container %s "
                            "was confirmed absent",
                            task_id,
                            task.status.value,
                            container_reference,
                        )
                        return
                    except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
                        should_retry = True
                        if attempt == 1 or attempt % 10 == 0:
                            logger.warning(
                                "Deferred Docker recovery for task %s is still waiting "
                                "for container %s (attempt=%s): %s",
                                task_id,
                                container_reference,
                                attempt,
                                exc,
                            )
                    except Exception as exc:  # noqa: BLE001
                        should_retry = True
                        logger.warning(
                            "Deferred Docker recovery for task %s could not inspect "
                            "container %s (attempt=%s): %s",
                            task_id,
                            container_reference,
                            attempt,
                            exc,
                        )
                    else:
                        await db.refresh(task)
                        if task.status != TaskStatus.RUNNING:
                            continue
                        cancellation_requested = isinstance(
                            getattr(task, "cancel_requested_at", None),
                            datetime,
                        )
                        cancellation_stop_failed = False
                        if cancellation_requested and container.status == "running":
                            try:
                                await _stop_recovered_cancelled_container(container, task_id)
                            except Exception as exc:  # noqa: BLE001
                                should_retry = True
                                cancellation_stop_failed = True
                                logger.warning(
                                    "Deferred recovery found cancelled task %s but could "
                                    "not stop container %s: %s",
                                    task_id,
                                    container_reference,
                                    exc,
                                )
                        if cancellation_stop_failed:
                            pass
                        elif container.status not in ("running", "exited"):
                            recovered_status = container.status
                            cleanup_ready = True
                            if recovered_status not in _QUIESCENT_CONTAINER_STATUSES:
                                try:
                                    await _stop_recovered_cancelled_container(container, task_id)
                                except Exception as exc:  # noqa: BLE001
                                    should_retry = True
                                    cleanup_ready = False
                                    logger.warning(
                                        "Deferred recovery could not stop non-runnable "
                                        "container %s for task %s: %s",
                                        container_reference,
                                        task_id,
                                        exc,
                                    )
                            if cleanup_ready:
                                try:
                                    await _finalize_recovered_raw_logs(
                                        db,
                                        docker,
                                        task,
                                        container,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    should_retry = True
                                    cleanup_ready = False
                                    logger.warning(
                                        "Deferred recovery could not finalize raw logs for "
                                        "task %s container %s: %s",
                                        task_id,
                                        container_reference,
                                        exc,
                                    )
                            if cleanup_ready:
                                try:
                                    await asyncio.to_thread(
                                        container.remove,
                                        force=True,
                                        v=True,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    should_retry = True
                                    logger.warning(
                                        "Deferred recovery found task %s container %s in "
                                        "status %s but could not remove it: %s",
                                        task_id,
                                        container_reference,
                                        container.status,
                                        exc,
                                    )
                                else:
                                    task.status = (
                                        TaskStatus.CANCELLED
                                        if cancellation_requested
                                        else TaskStatus.FAILED
                                    )
                                    task.error_message = (
                                        "Cancelled by user; recovered worker container was removed"
                                        if cancellation_requested
                                        else (
                                            "Task worker container was not runnable after scheduler "
                                            f"recovery (status={recovered_status})"
                                        )
                                    )
                                    task.container_id = None
                                    task.completed_at = utcnow()
                                    await self._release_issue_lock(
                                        db,
                                        issue_id=task.issue_id,
                                        owner_task_id=task.id,
                                    )
                                    await db.commit()
                                    self._running_tasks.discard(task_id)
                                    self._running_issues.discard(task.issue_id)
                                    logger.error(
                                        "Deferred recovery removed non-runnable container %s "
                                        "and marked task %s failed",
                                        container_reference,
                                        task_id,
                                    )
                                    return
                        else:
                            resume_context = (container.name, connection)
                            logger.info(
                                "Docker daemon recovered for task %s after %s attempt(s); "
                                "resuming container %s on %s (status=%s)",
                                task_id,
                                attempt,
                                container.name,
                                connection.host,
                                container.status,
                            )

                if resume_context is not None:
                    await self._resume_task_background(task_id, *resume_context)
                    return
                if should_retry:
                    await asyncio.sleep(_RECOVERY_UNAVAILABLE_RETRY_SECONDS)
        finally:
            current = asyncio.current_task()
            if self._worker_tasks.get(task_id) is current:
                self._worker_tasks.pop(task_id, None)
            logger.info("Deferred Docker recovery coordinator stopped for task %s", task_id)

    async def _resume_task_background(
        self,
        task_id: int,
        container_name: str,
        recovery_connection: DockerConnectionConfig | None = None,
    ) -> None:
        """Resume monitoring a task in the background thread pool."""
        self._active_worker_threads += 1
        t_submit = time.time()
        logger.info(
            f"Task {task_id} resume submitted to thread pool "
            f"(active_threads={self._active_worker_threads}, "
            f"max_workers={_worker_executor._max_workers})"
        )
        defer_recovery = False
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_resume_task,
                task_id,
                container_name,
                recovery_connection,
            )
            elapsed = time.time() - t_submit
            if success:
                logger.info(f"Resumed task {task_id} completed successfully (total={elapsed:.0f}s)")
            else:
                logger.error(f"Resumed task {task_id} failed (total={elapsed:.0f}s)")
        except (DockerConnectionsUnavailableError, TaskContainerLookupError) as e:
            defer_recovery = True
            logger.warning(
                "Resumed task %s lost a conclusive Docker view; returning it to "
                "deferred recovery: %s",
                task_id,
                e,
            )
        except Exception as e:
            logger.exception(f"Resumed task {task_id} failed with exception: {e}")
            await self._mark_worker_bootstrap_failed(task_id, e)
        finally:
            self._active_worker_threads -= 1
            if defer_recovery:
                recovery_task = asyncio.create_task(
                    self._coordinate_unavailable_recovery(task_id)
                )
                self._worker_tasks[task_id] = recovery_task
                self._terminal_worker_seen_at.pop(task_id, None)
                logger.info(
                    "Deferred recovery coordinator restarted for task %s after resume lookup",
                    task_id,
                )
            else:
                self._worker_tasks.pop(task_id, None)
                self._terminal_worker_seen_at.pop(task_id, None)
                self._running_tasks.discard(task_id)
                try:
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(select(Task).where(Task.id == task_id))
                        task = result.scalar_one_or_none()
                        if task:
                            lock_result = await db.execute(
                                select(IssueExecutionLock).where(
                                    IssueExecutionLock.issue_id == task.issue_id
                                )
                            )
                            lock = lock_result.scalar_one_or_none()
                            if lock is None or lock.task_id == task_id:
                                if self._block_issue_for_retained_container(task):
                                    logger.warning(
                                        "Keeping Issue %s locked because terminal resumed "
                                        "task %s retains container %s",
                                        task.issue_id,
                                        task_id,
                                        task.container_id,
                                    )
                                else:
                                    self._running_issues.discard(task.issue_id)
                                    await self._release_issue_lock(
                                        db,
                                        issue_id=task.issue_id,
                                        owner_task_id=task_id,
                                    )
                                    await db.commit()
                                    await self._maybe_complete_issue(db, task.issue_id)
                except Exception:
                    logger.exception("Failed to release lock for resumed task %s", task_id)


# Singleton scheduler instance
_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    """Get singleton scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


async def start_scheduler() -> None:
    """Start the scheduler in background."""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler() -> None:
    """Stop the scheduler."""
    if _scheduler:
        await _scheduler.stop()


def _run_worker_task(task_id: int) -> bool:
    """Run worker task in a separate thread with its own event loop.

    This function creates a new asyncio event loop and database connection for the thread.

    Args:
        task_id: Task ID to execute

    Returns:
        True if successful, False otherwise
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import _database_url

    # Create new event loop for this thread BEFORE creating the engine,
    # so asyncpg binds to this thread's loop rather than the scheduler's main loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = create_async_engine(
        _database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    ThreadSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.core.worker import WorkerExecutor
    from app.core.worker_command_pump import run_pump_until_task_ends

    async def run_task():
        pump_task = loop.create_task(
            run_pump_until_task_ends(
                task_id,
                session_factory=ThreadSessionLocal,
                owner=f"scheduler-thread-{task_id}",
            )
        )
        try:
            async with ThreadSessionLocal() as db:
                worker = WorkerExecutor(session_factory=ThreadSessionLocal)
                return await worker.execute_task(db, task_id)
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except BaseException:  # noqa: BLE001 - cancellation cleanup
                pass

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def _run_worker_resume_task(
    task_id: int,
    container_name: str,
    recovery_connection: DockerConnectionConfig | None = None,
) -> bool:
    """Resume monitoring a worker task in a separate thread with its own event loop.

    Similar to _run_worker_task but calls WorkerExecutor.resume_task()
    which attaches to an existing container instead of creating a new one.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import _database_url

    # Create new event loop for this thread BEFORE creating the engine,
    # so asyncpg binds to this thread's loop rather than the scheduler's main loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = create_async_engine(
        _database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    ThreadSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.core.worker import WorkerExecutor

    async def run_task():
        async with ThreadSessionLocal() as db:
            if recovery_connection is None:
                worker = WorkerExecutor(session_factory=ThreadSessionLocal)
            else:
                worker = WorkerExecutor(
                    docker_client=get_docker_client(recovery_connection),
                    session_factory=ThreadSessionLocal,
                )
            return await worker.resume_task(db, task_id, container_name)

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
